"""Pipeline orchestrator: tie stages together, support partial runs + interactive mode."""

import json
import logging
import os
import sys
from datetime import UTC, datetime

from agent_core.pipeline import filter as filter_mod
from agent_core.pipeline import match, search

logger = logging.getLogger(__name__)
STAGE_ORDER = ["search", "filter", "enrich", "match"]
DASHBOARD_URL = "http://localhost:8765"

# Whether the DB-writing helpers below have already warned about being
# skipped under a test environment (warn once, not once per call).
_TEST_GUARD_WARNED = False


def _is_test_environment() -> bool:
    """True when running under pytest or with AGENT_TESTING=1.

    Guards the _save_* helpers so no test path can accidentally write into
    the real data/agent.db. Real incident: chat tool tests (tests/test_chat.py)
    reached orchestrator._save_jobs_to_db via ToolDispatcher._search_jobs and
    polluted the production database with fake jobs (id=1 / byd1, "http://x"
    placeholder URLs). Keep this check cheap and side-effect free.
    """
    if os.environ.get("AGENT_TESTING") == "1":
        return True
    return "pytest" in sys.modules


def _is_production_db(db_path: str) -> bool:
    """True when db_path resolves to the real production database.

    Only writes aimed at the production DB are guarded: tests that pass an
    explicit tmp_path db (legitimate isolated writes) must keep working.
    """
    try:
        return os.path.realpath(db_path) == os.path.realpath("data/agent.db")
    except (OSError, ValueError):
        return False


def _guard_skip(what: str):
    """Log (once) that a DB write is skipped under a test environment."""
    global _TEST_GUARD_WARNED
    if not _TEST_GUARD_WARNED:
        _TEST_GUARD_WARNED = True
        logger.warning(
            "Skipping %s: test environment detected (pytest/AGENT_TESTING) — "
            "no writes to the real database",
            what,
        )


def _open_dashboard() -> None:
    """Ensure dashboard process is running, then open browser."""
    from agent_core.server.serve import _ensure_dashboard

    was_already_running = _ensure_dashboard()
    if was_already_running:
        return  # Dashboard already open, don't open a duplicate tab
    import webbrowser

    webbrowser.open(DASHBOARD_URL)


def _save_jobs_to_db(jobs, db_path="data/agent.db"):
    """Upsert jobs into SQLite so the Dashboard can display them.

    Search re-runs must never destroy manual state:
      - user_flag (感兴趣/不合适) is preserved on update
      - an already-enriched long JD is not overwritten by a short search-card
      - first_seen is preserved; is_new is 1 only for brand-new rows
    """
    if _is_test_environment() and _is_production_db(db_path):
        _guard_skip("_save_jobs_to_db (jobs)")
        return 0
    try:
        from agent_core.pipeline.search import _prefer_richer_description
        from agent_core.storage.db import get_db

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db(db_path)
        cur = conn.cursor()
        saved = 0
        for j in jobs:
            try:
                platforms = getattr(j, "platforms", "")
                if isinstance(platforms, str):
                    platforms_json = platforms
                elif isinstance(platforms, list | set):
                    platforms_json = json.dumps(list(platforms), ensure_ascii=False)
                else:
                    platforms_json = "[]"

                urls = getattr(j, "urls", {}) or {}
                if isinstance(urls, str):
                    urls_json = urls
                else:
                    urls_json = json.dumps(urls, ensure_ascii=False)

                job_id = getattr(j, "id", "")
                existing = cur.execute(
                    "SELECT first_seen, description, security_id, lid FROM jobs WHERE id=?",
                    (job_id,),
                ).fetchone()
                first_seen = existing[0] if existing else now
                published_at = getattr(j, "published_at", "") or ""
                description = getattr(j, "description", "") or ""
                security_id = getattr(j, "security_id", "") or ""
                lid = getattr(j, "lid", "") or ""

                if existing:
                    old_description = existing[1] or ""
                    if not _prefer_richer_description(description, old_description):
                        description = old_description
                    security_id = security_id or existing[2] or ""
                    lid = lid or existing[3] or ""
                    cur.execute(
                        """UPDATE jobs SET
                               title=?, company=?, company_normalized=?, location=?,
                               salary_min=?, salary_max=?, description=?, platforms=?,
                               urls=?, direction=?, last_seen=?, is_new=0,
                               security_id=?, lid=?, published_at=?
                           WHERE id=?""",
                        (
                            getattr(j, "title", ""),
                            getattr(j, "company", ""),
                            getattr(j, "company_normalized", getattr(j, "company", "")),
                            getattr(j, "location", ""),
                            getattr(j, "salary_min", None),
                            getattr(j, "salary_max", None),
                            description,
                            platforms_json,
                            urls_json,
                            getattr(j, "direction", ""),
                            now,
                            security_id,
                            lid,
                            published_at,
                            job_id,
                        ),
                    )
                    saved += cur.rowcount or 1
                else:
                    cur.execute(
                        """INSERT INTO jobs
                               (id, title, company, company_normalized, location,
                                salary_min, salary_max, description, platforms, urls,
                                direction, first_seen, last_seen, is_new,
                                security_id, lid, published_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                        (
                            job_id,
                            getattr(j, "title", ""),
                            getattr(j, "company", ""),
                            getattr(j, "company_normalized", getattr(j, "company", "")),
                            getattr(j, "location", ""),
                            getattr(j, "salary_min", None),
                            getattr(j, "salary_max", None),
                            description,
                            platforms_json,
                            urls_json,
                            getattr(j, "direction", ""),
                            first_seen,
                            now,
                            security_id,
                            lid,
                            published_at,
                        ),
                    )
                    saved += 1
            except Exception as e:
                logger.warning(f"Failed to save job {getattr(j, 'id', '?')}: {e}")
        conn.commit()
        conn.close()
        logger.info(f"Saved {saved} jobs to DB for dashboard")
        return saved
    except Exception as e:
        logger.warning(f"Failed to save jobs to DB: {e}")
        return 0


def _show_job_summary(jobs, title, max_show=10):
    """Print a compact job summary to the console."""
    print(f"\n{'=' * 60}")
    print(f"  {title}: {len(jobs)} 个岗位")
    print(f"{'=' * 60}")
    if not jobs:
        print("  (无)")
        return

    sorted_jobs = sorted(jobs, key=lambda j: j.salary_max or 0, reverse=True)
    for i, j in enumerate(sorted_jobs[:max_show]):
        # Some platforms (tencent/netease/...) only return one bound or none;
        # guard each bound separately so a None salary_min cannot crash the
        # summary (salary_min / 1000 would raise TypeError).
        if j.salary_min and j.salary_max:
            salary = f"{j.salary_min / 1000:.0f}-{j.salary_max / 1000:.0f}K"
        elif j.salary_max:
            salary = f"{j.salary_max / 1000:.0f}K"
        elif j.salary_min:
            salary = f"{j.salary_min / 1000:.0f}K+"
        else:
            salary = "面议"
        direction_tag = (
            f"[{getattr(j, 'direction', '')}]" if hasattr(j, "direction") and j.direction else ""
        )
        print(
            f"  {i + 1}. [{j.platforms}] {j.title} @ {j.company}  {salary}  {j.location}  {direction_tag}"
        )
    if len(jobs) > max_show:
        print(f"  ... 还有 {len(jobs) - max_show} 个岗位")


def _save_match_to_db(matched, db_path="data/agent.db"):
    """Save LLM match results to the match_results table.

    Stores the chain-of-thought reasoning alongside each score (added
    2026-07-06) so every match score is auditable. Falls back gracefully
    for legacy callers that don't supply reasoning/prompt_version.
    """
    if _is_test_environment() and _is_production_db(db_path):
        _guard_skip("_save_match_to_db (match results)")
        return
    try:
        from agent_core.storage.db import get_db

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db(db_path)
        cur = conn.cursor()
        saved = 0
        for m in matched:
            # raw_score is the new schema field; fall back to legacy "score"
            score = m.get("raw_score", m.get("score", 0))
            # The v2-reasoning-chain prompt emits "gaps" (未命中的硬性要求).
            # Older prompts emitted "missing_skills". Persist whichever is
            # present so the dashboard's "未命中技能" column isn't always empty.
            missing = m.get("gaps")
            if missing is None:
                missing = m.get("missing_skills", [])
            cur.execute(
                """INSERT OR REPLACE INTO match_results
                   (job_id, match_score, match_reason, missing_skills, strengths,
                    job_title, company, direction, created_at,
                    reasoning, prompt_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    m.get("job_id", ""),
                    score,
                    m.get("match_reason", ""),
                    json.dumps(missing, ensure_ascii=False),
                    json.dumps(m.get("strengths", []), ensure_ascii=False),
                    m.get("job_title", ""),
                    m.get("company", ""),
                    m.get("direction", ""),
                    now,
                    m.get("reasoning", ""),
                    m.get("prompt_version", "v1"),
                ),
            )
            saved += 1
        conn.commit()
        conn.close()
        logger.info(f"Saved match results for {saved} jobs")
        _save_pipeline_run("match", len(matched), db_path)
    except Exception as e:
        logger.warning(f"Failed to save match results to DB: {e}")


def _save_pipeline_run(stage, job_count, db_path="data/agent.db"):
    """Log a pipeline stage completion with timestamp."""
    if _is_test_environment() and _is_production_db(db_path):
        _guard_skip("_save_pipeline_run")
        return
    try:
        from agent_core.storage.db import get_db

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db(db_path)
        conn.execute(
            "INSERT INTO pipeline_runs (stage, job_count, created_at) VALUES (?, ?, ?)",
            (stage, job_count, now),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _save_search_statuses(statuses, db_path="data/agent.db", search_id=""):
    """Persist per-platform search results for the Dashboard search audit."""
    if _is_test_environment() and _is_production_db(db_path):
        _guard_skip("_save_search_statuses")
        return
    if not statuses:
        return
    try:
        from agent_core.storage.db import get_db

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db(db_path)
        for st in statuses:
            conn.execute(
                """INSERT INTO search_status
                       (search_id, platform, status, result_count, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    search_id or f"search_{now}",
                    st.get("platform", ""),
                    st.get("status", "no_results"),
                    st.get("result_count", 0),
                    st.get("error_message", "") or "",
                    now,
                ),
            )
        conn.commit()
        conn.close()
        logger.info(f"Saved {len(statuses)} per-platform search status rows")
    except Exception as e:
        logger.warning(f"Failed to save search statuses: {e}")


def _ask_continue(stage_name, job_count):
    """Ask user whether to continue to the next stage. Returns True to continue."""
    if job_count == 0:
        print(f"\n[!] {stage_name} 阶段返回 0 个岗位。")
    print("\n>>> 继续下一步？(回车继续 / 'q' 退出 / 's' 跳过后续直接看结果): ", end="")
    try:
        choice = input().strip().lower()
        if choice == "q":
            print("[!] 用户终止 pipeline。")
            return False
        elif choice == "s":
            print("[!] 跳过后续阶段，输出当前结果。")
            return "skip"
    except (EOFError, KeyboardInterrupt):
        print("\n[!] 输入中断，终止 pipeline。")
        return False
    return True


async def _compare_jobs(matched: list[dict], config, llm_provider) -> str:
    """Cross-job comparison: ask LLM to rank matched jobs and pick top picks.

    Feeds all match results (score + reason + gaps) to a single LLM call
    and asks for a ranked recommendation with reasoning. This gives the
    user a relative comparison that per-job scoring alone cannot provide.
    """
    from agent_core.llm.providers import call_llm_with_retry

    job_summaries = []
    for i, m in enumerate(matched, 1):
        score = m.get("raw_score", m.get("score", "?"))
        gaps = m.get("gaps", m.get("missing_skills", [])) or []
        # v4-gap-grading emits gaps as [{gap, severity, reason}, ...] objects,
        # while older prompts emitted plain strings. Normalize both so the
        # join cannot raise TypeError (previously swallowed silently).
        gap_labels = []
        for g in gaps[:3]:
            if isinstance(g, dict):
                gap_labels.append(str(g.get("gap") or g.get("reason") or g))
            else:
                gap_labels.append(str(g))
        gaps_str = "、".join(gap_labels) if gap_labels else "无"
        job_summaries.append(
            f"{i}. [{score}%] {m.get('job_title', '?')} @ {m.get('company', '?')}"
            f" | 缺失: {gaps_str}"
            f" | {m.get('match_reason', '')}"
        )

    prompt = (
        "你是一位求职顾问。以下是对同一个简历的多个岗位匹配结果，"
        "请综合比较后给出建议：\n\n"
        + "\n\n".join(job_summaries)
        + "\n\n请按以下格式输出（简洁，不超过 500 字）：\n"
        "🏆 首选推荐：<岗位名> @ <公司> — <一句话理由>\n"
        "🥈 次选推荐：<岗位名> @ <公司> — <一句话理由>\n"
        "🥉 第三推荐：<岗位名> @ <公司> — <一句话理由>\n"
        "💡 总体建议：<2-3 句话，关于求职策略>"
    )

    try:
        response = await call_llm_with_retry(
            llm_provider,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        return response.strip()
    except Exception as e:
        logger.warning(f"Cross-job comparison failed: {e}")
        return ""


async def run_pipeline(
    config,
    llm_provider,
    stages=None,
    keywords=None,
    directions=None,
    platforms=None,
    headless=False,
    interactive=True,
    max_pages=None,
):
    """Run the job search/match pipeline, pausing between stages when interactive=True."""
    if stages is None:
        stages = STAGE_ORDER
    stage_set = set(stages)
    data = {"jobs": [], "filtered": [], "matched": []}

    # ── Stage 1: Search ──
    if "search" in stage_set:
        statuses: list[dict] = []
        jobs = await search.search_all(
            config,
            platforms,
            directions,
            keywords=keywords,
            headless=headless,
            max_pages=max_pages,
            status_sink=statuses,
        )
        data["jobs"] = jobs
        data["search_statuses"] = statuses
        logger.info(f"Search: {len(jobs)} jobs after dedup")

        if jobs:
            _save_jobs_to_db(jobs)
            _save_pipeline_run("search", len(jobs))
        _save_search_statuses(statuses)

        if interactive:
            _show_job_summary(jobs, "🔍 搜索完成")
            if jobs:
                _open_dashboard()
                print(f"  📊 Dashboard 已打开: {DASHBOARD_URL}")
            choice = _ask_continue("搜索", len(jobs))
            if choice is False:
                return data
            if choice == "skip":
                return data

    # ── Stage 2: Filter ──
    if "filter" in stage_set:
        source = data["jobs"] or []
        filtered = filter_mod.filter_jobs(source, config)
        data["filtered"] = filtered
        logger.info(f"Filter: {len(source)} -> {len(filtered)}")

        if interactive:
            removed = len(source) - len(filtered)
            _show_job_summary(filtered, f"🔍 过滤后 (排除{removed}个)")
            choice = _ask_continue("过滤", len(filtered))
            if choice is False:
                return data
            if choice == "skip":
                return data

    # ── Stage 2.5: Enrich (lazy, before match) ──
    # Enrichment ONLY runs for jobs marked as 'interested' by user.
    # This avoids unnecessary JD fetches for jobs the user won't apply to.
    # Governed by matching.enrich_in_pipeline (default False): when False the
    # pipeline skips JD fetching entirely -- the dashboard's dedicated
    # /api/jd/fetch + /api/match/run path is the primary enrich entrypoint,
    # and CLI users can run `rematch <id>` (which enriches on demand) or set
    # enrich_in_pipeline: true to enrich during pipeline runs.
    if "match" in stage_set and getattr(config.matching, "enrich_in_pipeline", False):
        from agent_core.pipeline.enrichment import enrich_job_jd

        # Step 1: Get all candidate jobs
        source = data.get("filtered") or data.get("jobs") or []

        # Step 2: Filter to ONLY user-flagged (interested) jobs
        flagged_only = getattr(config.matching, "match_flagged_only", True)
        if flagged_only:
            from agent_core.storage.db import get_db

            flagged_ids = set()
            try:
                conn = get_db()
                for row in conn.execute(
                    "SELECT id FROM jobs WHERE user_flag = 'interested'"
                ).fetchall():
                    flagged_ids.add(row[0])
                conn.close()
            except Exception:
                pass

            if flagged_ids:
                before = len(source)
                source = [j for j in source if j.id in flagged_ids]
                logger.info(
                    f"Enrichment flagged-only: {before} candidates → {len(source)} marked as interested"
                )

        # Step 3: Enrich only the flagged jobs.
        # First, reload descriptions from DB — the Dashboard "抓取JD" may
        # have already enriched them. This avoids redundant API calls that
        # waste Boss tokens and risk anti-bot triggers.
        enrich_top_n = getattr(config.matching, "enrich_top_n", None)
        if enrich_top_n:
            to_enrich = sorted(source, key=lambda j: j.salary_max or 0, reverse=True)[:enrich_top_n]
        else:
            to_enrich = source
        if not to_enrich:
            logger.info("Enrichment: no jobs to enrich after flag filter")
            data["enriched"] = 0
        else:
            # Reload descriptions from DB (dashboard "抓取JD" may already
            # have enriched them) -- avoids redundant API calls that waste
            # Boss tokens and risk anti-bot triggers.
            _db_descriptions: dict[str, str] = {}
            try:
                conn = get_db()
                rows = conn.execute(
                    "SELECT id, description FROM jobs WHERE id IN ({})".format(
                        ",".join("?" for _ in to_enrich)
                    ),
                    [j.id for j in to_enrich],
                ).fetchall()
                _db_descriptions = {r[0]: r[1] or "" for r in rows}
                conn.close()
            except Exception:
                pass
            for j in to_enrich:
                db_desc = _db_descriptions.get(j.id, "")
                if db_desc and len(db_desc) > len(j.description or ""):
                    j.description = db_desc

            enriched_count = 0
            logger.info(f"Enrichment: starting JD fetch for {len(to_enrich)} interested jobs...")
            for idx, j in enumerate(to_enrich, 1):
                # Skip if already enriched (description already has JD: prefix or >200 chars)
                if len(j.description or "") > 200 and "JD:" in (j.description or ""):
                    enriched_count += 1
                    continue
                try:
                    await enrich_job_jd(j, config)
                    enriched_count += 1
                    if idx % 5 == 0 or idx == len(to_enrich):
                        logger.info(f"  enriched {enriched_count}/{len(to_enrich)}")
                except Exception as e:
                    logger.warning(f"Enrich failed for {j.id} ({j.title}): {e}")
            logger.info(f"Enrichment: {enriched_count}/{len(to_enrich)} jobs enriched")
            data["enriched"] = enriched_count

    # ── Stage 4: Match (LLM) ──
    if "match" in stage_set:
        source = data.get("filtered") or data.get("jobs") or []

        # Filter to only user-flagged (interested) jobs
        flagged_only = getattr(config.matching, "match_flagged_only", True)
        if flagged_only:
            from agent_core.storage.db import get_db

            flagged_ids = set()
            try:
                conn = get_db()
                for row in conn.execute(
                    "SELECT id FROM jobs WHERE user_flag = 'interested'"
                ).fetchall():
                    flagged_ids.add(row[0])
                conn.close()
            except Exception:
                pass

            if flagged_ids:
                before = len(source)
                source = [p for p in source if p.id in flagged_ids]
                logger.info(
                    f"Match flagged-only: {before} filtered → {len(source)} flagged as interested"
                )
            else:
                logger.info("Match flagged-only: no flagged jobs, matching will be skipped")

        if not source:
            logger.info("Match: no jobs to match after flag filter")
            matched, skipped = [], 0
            data["matched"] = matched
            data["skipped"] = skipped
        else:
            if interactive:
                print("\n[LLM] 正在进行深度匹配 (DeepSeek)，请耐心等待...")
            # match_jobs expects items with .job/.resume_file/.direction, not raw Job
            from types import SimpleNamespace

            _items = [
                SimpleNamespace(job=j, resume_file="", direction=j.direction or "") for j in source
            ]
            matched, skipped = await match.match_jobs(_items, config, llm_provider)
            data["matched"] = matched
            data["skipped"] = skipped
        logger.info(f"Match: {len(matched)} results (skipped {skipped} on error)")
        for m in matched:
            # raw_score is the v2 schema; fall back to legacy "score"
            _s = m.get("raw_score", m.get("score", "?"))
            logger.info(f"  {_s}% {m.get('job_title', '?')} @ {m.get('company', '?')}")

        if matched:
            _save_match_to_db(matched)

        # Cross-job comparison: rank all matched jobs relative to each other
        if matched and len(matched) >= 2 and llm_provider:
            try:
                summary = await _compare_jobs(matched, config, llm_provider)
                if summary:
                    data["comparison"] = summary
                    if interactive:
                        print(f"\n{'=' * 60}")
                        print("  📊 横向对比")
                        print(f"{'=' * 60}")
                        print(summary)
            except Exception:
                logger.debug("Cross-job comparison skipped", exc_info=True)

        if interactive:
            print(f"\n{'=' * 60}")
            print(f"  🎯 LLM 匹配完成: {len(matched)} 个匹配 (跳过 {skipped} 个)")
            print(f"{'=' * 60}")
            for m in matched[:15]:
                _s = m.get("raw_score", m.get("score", "?"))
                print(f"  {_s}% {m.get('job_title', '?')} @ {m.get('company', '?')}")
            if len(matched) > 15:
                print(f"  ... 还有 {len(matched) - 15} 个")

    # ── Toast ──
    try:
        from agent_core.notify.windows_toast import notify_search_complete

        total = len(data.get("matched", []) or data.get("jobs", []))
        notify_search_complete(total, data.get("skipped", 0))
    except Exception as e:
        logger.debug(f"Toast notify skipped: {e}")

    return data
