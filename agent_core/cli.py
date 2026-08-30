"""Typer CLI: job-agent entrypoint."""

import asyncio
import logging
import sys

import typer

from agent_core.llm.providers import create_provider

app = typer.Typer(name="job-agent", help="求职 AI Agent")
logger = logging.getLogger("agent_core")


def _setup(config_path="config.yaml"):
    from agent_core.config import load_config, project_root_anchor
    from agent_core.llm.providers import create_provider
    from agent_core.storage.db import get_db, migrate

    # Ensure UTF-8 output on Windows (emojis break GBK in cmd.exe)
    if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    # 锚定项目根: data/ 日志目录 + get_db 默认路径都指向项目根, 使 CLI 从任意
    # cwd 运行也能读写正确的 data/agent.db 与 data/agent.log。
    # 此前仅为相对 cwd 路径——从项目根外部运行会把 data/ 错建到 cwd(2026-08-30 实测)。
    import os as _os

    root = project_root_anchor()
    data_dir = str(root / "data")
    _os.makedirs(data_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(root / "data" / "agent.log"), encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    config = load_config(config_path)
    db = get_db(str(root / "data" / "agent.db"))
    migrate(db)
    # Tolerate missing API key: non-LLM commands (login, search, status) still
    # work without it. LLM commands call _require_provider() for a clear error.
    provider = create_provider(config) if config.api_key else None
    if provider is None and config.api_key == "":
        logger.warning(f"{config.llm.api_key_env} not set — LLM commands unavailable")
    return config, db, provider


def _require_provider(provider, config):
    """Guard for commands that need the LLM. Gives a clear error instead of NoneType crash."""
    if provider is None:
        raise typer.Exit(
            f"LLM unavailable: set {config.llm.api_key_env} environment variable "
            f'(e.g. setx {config.llm.api_key_env} "sk-your-key").'
        )
    return provider


@app.command()
def login(
    platform: str = typer.Option("", "--platform", help="Platform: boss, liepin, zhilian"),
):
    """登录/刷新招聘平台 Cookie（浏览器弹窗手动扫码/登录）"""
    config, _, _ = _setup()

    # Accept short aliases documented in help/README (boss -> boss_zhipin)
    _ALIASES = {
        "boss": "boss_zhipin",
        "liepin": "liepin",
        "51": "job51",
        "zhipin": "boss_zhipin",
        "zl": "zhilian",
    }
    platform = _ALIASES.get(platform, platform)

    if not platform:
        typer.echo("Use --platform boss|liepin|zhilian to login.")
        return
    if platform not in config.platforms:
        typer.echo(f"Unknown platform: {platform}")
        raise typer.Exit(1)

    import asyncio

    async def _do_login():
        try:
            if platform == "boss_zhipin":
                from agent_core.platforms.boss_zhipin import boss_login

                await boss_login(config.platforms[platform].cookie_path)
            elif platform == "liepin":
                from agent_core.platforms.liepin import liepin_login

                await liepin_login(config.platforms[platform].cookie_path)
            elif platform == "zhilian":
                from agent_core.platforms.zhilian import zhilian_login

                try:
                    await zhilian_login(config.platforms[platform].cookie_path)
                finally:
                    pass
            else:
                typer.echo(f"Login not yet implemented for {platform}")
        finally:
            if platform == "zhilian":
                try:
                    from agent_core.platforms.zhilian_browser import close_browser

                    await close_browser()
                except Exception:
                    pass

    asyncio.run(_do_login())


@app.command()
def rematch(
    job_id: str = typer.Argument("", help="Job ID to rematch"),
    all_since: str = typer.Option("", "--all-since", help="Date YYYY-MM-DD"),
):
    """Re-run matching for a job or all jobs since a date (after resume update).

    Results are persisted to match_results (overwriting prior scores) so the
    Dashboard match tab reflects the new scores. match_jobs returns dicts with
    ``raw_score`` (v4 schema); legacy ``score`` is honored as a fallback.
    """
    config, db, provider = _setup()
    provider = create_provider(config, thinking_effort="max")
    import asyncio

    from agent_core.pipeline.enrichment import enrich_job_jd
    from agent_core.pipeline.match import match_jobs
    from agent_core.pipeline.orchestrator import _save_match_to_db
    from agent_core.platforms.base import Job

    class _Item:
        """Lightweight wrapper match_jobs expects (item.job/.resume_file/.direction)."""

        pass

    def _wrap(_job):
        it = _Item()
        it.job = _job  # type: ignore[attr-defined]
        it.resume_file = ""  # type: ignore[attr-defined]
        it.direction = _job.direction or ""  # type: ignore[attr-defined]
        return it

    def _score(r):
        return r.get("raw_score", r.get("score", "?"))

    if job_id:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            typer.echo(f"Job not found: {job_id}")
            return
        job = Job.from_storage(row)
        # Enrich with full JD on-demand (single job only, not batch)
        job = asyncio.run(enrich_job_jd(job, config))
        results, _skipped = asyncio.run(match_jobs([_wrap(job)], config, provider))
        if results:
            _save_match_to_db(results)
        for r in results:
            typer.echo(
                f"  {_score(r)}% {r.get('job_title', '?')} @ {r.get('company', '?')}"
                f" ({r.get('confidence', '?')})"
            )
            typer.echo(f"    {r.get('match_reason', '')}")
    elif all_since:
        rows = db.execute("SELECT * FROM jobs WHERE last_seen >= ?", (all_since,)).fetchall()
        if not rows:
            typer.echo(f"No jobs since {all_since}")
            return
        jobs = [Job.from_storage(dict(r)) for r in rows]
        ps = [_wrap(j) for j in jobs]
        typer.echo(f"Re-matching {len(ps)} jobs since {all_since}...")
        results, _skipped = asyncio.run(match_jobs(ps, config, provider))
        if results:
            _save_match_to_db(results)
        for r in results[:10]:
            typer.echo(f"  {_score(r)}% {r.get('job_title', '?')} @ {r.get('company', '?')}")
    else:
        typer.echo(
            "Usage: job-agent rematch <job-id>     OR     job-agent rematch --all-since 2026-06-01"
        )


@app.command()
def search(
    direction: str = typer.Option("", "--direction"),
    platforms: str = typer.Option("", "--platforms"),
    keyword: str = typer.Option(
        ...,
        "--keyword",
        help=(
            "搜索关键词，多个用逗号分隔，如 'AI Agent,Python'。必填：不再使用 config 预置关键词。"
        ),
    ),
    company: str = typer.Option(
        "",
        "--company",
        help="按公司名过滤（大小写不敏感，子串匹配），如 '大疆'",
    ),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="每个平台/关键词抓取页数（覆盖 config 的 search_max_pages）",
    ),
):
    """Search jobs across platforms. --keyword is required (config presets are empty)."""
    config, _, _ = _setup()
    dirs = [direction] if direction else None
    plats_raw = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
    company_filter = company.strip() if company else None
    keywords = [k.strip() for k in keyword.split(",") if k.strip()] if keyword else None

    plats = None
    if plats_raw:
        from agent_core.pipeline.search import resolve_platform_names

        plats, unknown = resolve_platform_names(config, plats_raw)
        if unknown:
            typer.echo(f"未知平台: {', '.join(unknown)}")
        if not plats:
            raise typer.Exit(1)

    async def _run():
        try:
            from agent_core.pipeline.filter import filter_jobs
            from agent_core.pipeline.search import filter_by_company, search_all

            jobs = await search_all(config, plats, dirs, keywords=keywords, max_pages=max_pages)
            # CLI search follows the same config rules as pipeline search.
            jobs = filter_jobs(jobs, config)
            before = len(jobs)
            if company_filter:
                jobs = filter_by_company(jobs, company_filter)

            if company_filter:
                typer.echo(f"Found {before} jobs, {len(jobs)} match company '{company_filter}'")
            else:
                typer.echo(f"Found {len(jobs)} jobs")
            for j in jobs[:20]:
                typer.echo(f"  [{j.direction}] {j.title} @ {j.company} ({j.location})")

            # If zero results, check cookies and print diagnosis
            if len(jobs) == 0 and config.platforms:
                from agent_core.cookie_health import diagnose_empty_results

                diag = diagnose_empty_results(config)
                if diag:
                    typer.echo(diag)

            return jobs
        finally:
            try:
                from agent_core.platforms.zhilian_browser import close_browser

                await close_browser()
            except Exception:
                pass

    return asyncio.run(_run())


@app.command()
def pipeline(
    stages: str = typer.Option("search,filter,match", "--stages"),
    keyword: str = typer.Option(
        "",
        "--keyword",
        help="搜索关键词，多个用逗号分隔，如 'AI Agent,Python'。必填。",
    ),
    platforms: str = typer.Option(
        "",
        "--platforms",
        help="平台过滤，逗号分隔，如 'boss_zhipin,tencent'。默认全部。",
    ),
    direction: str = typer.Option("", "--direction"),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        help="每个平台/关键词抓取页数（覆盖 config 的 search_max_pages）",
    ),
):
    """Run full or partial pipeline."""
    config, _, provider = _setup()
    provider = create_provider(config, thinking_effort="max")
    stage_list = [s.strip() for s in stages.split(",")]
    keywords = [k.strip() for k in keyword.split(",") if k.strip()] if keyword else None
    dirs = [direction] if direction else None
    plats_raw = [p.strip() for p in platforms.split(",") if p.strip()] if platforms else None
    plats = None
    if plats_raw:
        from agent_core.pipeline.search import resolve_platform_names

        plats, unknown = resolve_platform_names(config, plats_raw)
        if unknown:
            typer.echo(f"未知平台: {', '.join(unknown)}")
        if not plats:
            raise typer.Exit(1)

    async def _run():
        from agent_core.pipeline.orchestrator import run_pipeline

        return await run_pipeline(
            config,
            provider,
            stages=stage_list,
            keywords=keywords,
            directions=dirs,
            platforms=plats,
            max_pages=max_pages,
        )

    data = asyncio.run(_run())
    matched = data.get("matched", [])
    if matched:
        typer.echo("\nTop matches:")
        for m in matched[:10]:
            # match.py v4 returns raw_score; legacy "score" honored as fallback
            _score = m.get("raw_score", m.get("score", "?"))
            typer.echo(f"  {_score}% {m.get('job_title', '?')} @ {m.get('company', '?')}")
            typer.echo(f"    {m.get('match_reason', '')}")
    else:
        typer.echo("No results. Try 'job-agent search' first.")
        # Check if cookies are the root cause
        if config.platforms:
            from agent_core.cookie_health import diagnose_empty_results

            diag = diagnose_empty_results(config)
            if diag:
                typer.echo(diag)


@app.command()
def tailor(
    job_id: str = typer.Argument(..., help="Job ID to tailor resume for"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip diff review and confirmation prompt"),
):
    """Generate tailored resume (.docx + .md) for a job, review diff, then save."""
    config, db, provider = _setup()
    provider = create_provider(config)
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    typer.echo(f"Tailoring resume for: {job.title} @ {job.company}")

    import asyncio

    from agent_core.config import load_resume
    from agent_core.pipeline.enrichment import enrich_job_jd
    from agent_core.pipeline.tailor import (
        diff_resumes,
        extract_hard_facts,
        open_job_link,
        save_resume,
        tailor_resume,
        verify_facts,
    )

    async def _run():
        try:
            # Enrich with full JD on-demand before tailoring
            enriched = await enrich_job_jd(job, config)
            text = await tailor_resume(enriched, config, provider)

            # Anti-hallucination review (B+E): verify hard facts survived, show diff.
            original = load_resume(config, enriched.direction)
            facts = extract_hard_facts(original)
            missing = verify_facts(text, facts)
            if missing:
                typer.echo(
                    typer.style(
                        f"⚠ 事实校验：{len(missing)} 项硬事实缺失/可能被改动：", fg="yellow"
                    )
                )
                for kind, v in missing[:20]:
                    typer.echo(f"  [{kind}] {v}")

            if not yes:
                typer.echo(typer.style("--- diff (原 vs 定制) ---", fg="cyan"))
                typer.echo(diff_resumes(original, text))
                import sys

                if sys.stdin.isatty():
                    if not typer.confirm("保存定制简历？", default=True):
                        typer.echo("已取消，未保存。")
                        return
                # non-interactive (e.g. tests, chat pipeline): proceed to save

            paths = save_resume(text, enriched)
            # Catalog so the Dashboard "已生成文件" tab shows job association
            from agent_core.pipeline.file_catalog import TYPE_TAILORED_RESUME, catalog_file

            for p in (paths["md"], paths["docx"]):
                catalog_file(
                    db,
                    job_id,
                    TYPE_TAILORED_RESUME,
                    p,
                    direction=enriched.direction,
                    company=enriched.company,
                    job_title=enriched.title,
                )
            typer.echo(f"Resume saved: {paths['docx']}")
            typer.echo(f"Preview:     {paths['md']}")
            open_job_link(enriched)
        finally:
            try:
                from agent_core.platforms.zhilian_browser import close_browser

                await close_browser()
            except Exception:
                pass

    asyncio.run(_run())


@app.command()
def serve(
    port: int = typer.Option(8765, "--port"),
    daemon: bool = typer.Option(
        False,
        "--daemon",
        help="以独立后台进程启动（退出终端后仍运行）",
    ),
    stop: bool = typer.Option(
        False,
        "--stop",
        help="停止后台 dashboard 进程",
    ),
):
    """启动本地 HTTP 仪表盘。"""
    if stop:
        from agent_core.server.serve import _stop_dashboard

        _stop_dashboard()
        return
    if daemon:
        from agent_core.server.serve import _ensure_dashboard

        _ensure_dashboard(port=port)
        typer.echo(f"Dashboard 后台进程已启动: http://localhost:{port}")
        typer.echo("  用 --stop 停止。")
        return
    from agent_core.server.serve import start_server

    start_server(port=port)


@app.command()
def track(
    action: str = typer.Argument("list"),
    target: str = typer.Argument("", help="job-id or app-id or external-url"),
    status: str = typer.Option("", "--status", help="Filter status or set new status"),
):
    """Track: add <job-id|url>, list [--status HR已读], show <id>, update <id> --status 二面."""
    _, db, _ = _setup()
    from agent_core.tracking.tracker import (
        add_application,
        create_timeline_table,
        get_application,
        get_timeline,
        list_applications,
        update_status,
    )

    create_timeline_table(db)

    if action == "add":
        if not target:
            typer.echo("Usage: job-agent track add <job-id-or-url>")
            return
        # Support external applications: if target is a URL, generate an ID
        import hashlib

        jid = (
            target
            if not target.startswith("http")
            else hashlib.md5(target.encode()).hexdigest()[:16]  # nosec B324 -- job ID, not security
        )
        aid = add_application(db, jid)
        typer.echo(f"Application #{aid} recorded (已投递)")

    elif action == "update":
        if not target or not status:
            typer.echo("Usage: job-agent track update <app-id> --status 二面")
            return
        try:
            update_status(db, int(target), status)
            typer.echo(f"#{target} -> {status}")
        except ValueError as e:
            typer.echo(f"Error: {e}")

    elif action == "show":
        if not target:
            typer.echo("Usage: job-agent track show <app-id>")
            return
        try:
            app = get_application(db, int(target))
            typer.echo(
                f"#{app['id']} [{app['status']}]"
                f" {app.get('job_title', '?')} @ {app.get('job_company', '?')}"
            )
            typer.echo(f"  Applied: {app['applied_at']} | Updated: {app['updated_at']}")
            # Timeline
            tl = get_timeline(db, int(target))
            if tl:
                typer.echo("  Timeline:")
                for t in tl:
                    typer.echo(f"    {t['created_at']}: {t['from_status']} -> {t['to_status']}")
        except ValueError as e:
            typer.echo(f"Error: {e}")

    elif action == "list":
        status_filter = status if status else None
        apps = list_applications(db, status_filter)
        if not apps:
            label = f" (filtered by '{status}')" if status else ""
            typer.echo(f"No applications{label}.")
            return
        for a in apps:
            m = {"Offer": "🟢", "入职": "🟢", "已终止": "🔴"}.get(a["status"], "🟡")
            typer.echo(
                f"  {m} #{a['id']} [{a['status']}]"
                f" {a.get('job_title', '?')} @ {a.get('job_company', '?')}"
            )
    else:
        typer.echo(f"Unknown: {action}. Try: list, add, show, update")


@app.command()
def cover_letter(job_id: str = typer.Argument(..., help="Job ID")):
    """Generate an HR outreach message (打招呼) for a job."""
    config, db, provider = _setup()
    provider = create_provider(config)
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    typer.echo(f"HR message: {job.title} @ {job.company}")
    import asyncio

    from agent_core.pipeline.cover_letter import generate_cover_letter, save_cover_letter
    from agent_core.pipeline.enrichment import enrich_job_jd

    async def _r():
        try:
            # Enrich with full JD on-demand before generating HR message
            enriched = await enrich_job_jd(job, config)
            text = await generate_cover_letter(enriched, config, provider)
            path = save_cover_letter(text, enriched)
            from agent_core.pipeline.file_catalog import TYPE_COVER_LETTER, catalog_file

            catalog_file(
                db,
                job_id,
                TYPE_COVER_LETTER,
                path,
                direction=enriched.direction,
                company=enriched.company,
                job_title=enriched.title,
            )
            typer.echo(text[:200] + "...")
            typer.echo(f"Saved: {path}")
        finally:
            try:
                from agent_core.platforms.zhilian_browser import close_browser

                await close_browser()
            except Exception:
                pass

    asyncio.run(_r())


@app.command()
def interview_prep(
    job_id: str = typer.Argument(..., help="Job ID"),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force regenerate even if a cached JSON exists"
    ),
):
    """Generate interview prep questions and save to output/."""
    config, db, provider = _setup()
    provider = create_provider(config)
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    typer.echo(f"Interview prep: {job.title} @ {job.company}")
    import asyncio

    from agent_core.pipeline.enrichment import enrich_job_jd
    from agent_core.pipeline.interview_prep import (
        load_interview_prep_json,
        predict_questions,
        save_interview_prep,
    )

    # C: 缓存复用 -- skip the LLM call if a cached JSON exists and --refresh not set
    if not refresh:
        cached = load_interview_prep_json(job_id, db)
        if cached:
            total = sum(len(r.get("questions", [])) for r in cached.get("rounds", []))
            typer.echo(f"Using cached prep (use --refresh to regenerate). {total} questions.")
            return

    async def _r():
        try:
            # Enrich with full JD on-demand before generating interview prep
            enriched = await enrich_job_jd(job, config)
            qs = await predict_questions(enriched, config, provider)
            md_path = save_interview_prep(qs, enriched)
            from agent_core.pipeline.file_catalog import TYPE_INTERVIEW_PREP, catalog_file

            # Catalog both md (human) and json (machine / mock-interview import)
            json_path = md_path[:-3] + ".json"
            for path in (md_path, json_path):
                catalog_file(
                    db,
                    job_id,
                    TYPE_INTERVIEW_PREP,
                    path,
                    direction=enriched.direction,
                    company=enriched.company,
                    job_title=enriched.title,
                )
            total_q = sum(len(r.get("questions", [])) for r in qs.get("rounds", []))
            typer.echo(
                f"Saved: {md_path}\nTotal: {total_q} questions across "
                f"{len(qs.get('rounds', []))} rounds"
            )
        finally:
            try:
                from agent_core.platforms.zhilian_browser import close_browser

                await close_browser()
            except Exception:
                pass

    asyncio.run(_r())


@app.command()
def mock_interview(
    job_id: str = typer.Argument(..., help="Job ID"),
    from_prep: bool = typer.Option(
        False, "--from-prep", help="Use the interview-prep question bank for this job"
    ),
    focus: str = typer.Option("", "--focus", help="Filter bank by keyword (e.g. 技术/项目深挖)"),
    difficulty: str = typer.Option("", "--difficulty", help="easy / normal / hard"),
):
    """Start an interactive mock interview in the terminal."""
    config, db, provider = _setup()
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        typer.echo(f"Job not found: {job_id}")
        return
    from agent_core.platforms.base import Job

    job = Job.from_storage(row)
    from agent_core.pipeline.interview_prep import mock_interview as mi

    mi(
        job,
        config,
        provider,
        from_prep=from_prep,
        focus=focus or None,
        difficulty=difficulty or None,
    )


@app.command()
def offer_eval(
    company: str = typer.Option(..., "--company"),
    title: str = typer.Option("", "--title"),
    location: str = typer.Option("", "--location"),
    salary: str = typer.Option("", "--salary"),
    bonus: str = typer.Option("", "--bonus"),
    benefits: str = typer.Option("", "--benefits"),
    level: str = typer.Option("", "--level"),
    notes: str = typer.Option("", "--notes"),
):
    """Evaluate a job offer."""
    config, _, provider = _setup()
    provider = create_provider(config)
    import asyncio

    from agent_core.pipeline.offer_eval import evaluate

    async def _r():
        r = await evaluate(
            config, provider, company, title, location, salary, bonus, benefits, level, notes
        )
        typer.echo(f"\n综合评价: {r['overall_score']}/10")
        typer.echo(
            f"竞争力: {r['competitive_score']}/10"
            f" | 成长性: {r['growth_score']}/10"
            f" | 风险: {r['risk_score']}/10"
        )
        typer.echo(f"\n{r['summary']}\n")
        typer.echo("优势:")
        for p in r.get("pros", []):
            typer.echo(f"  + {p}")
        typer.echo("劣势:")
        for c in r.get("cons", []):
            typer.echo(f"  - {c}")
        if r.get("negotiation_levers"):
            typer.echo("谈判杠杆:")
            for n in r["negotiation_levers"]:
                typer.echo(f"  > {n}")

    asyncio.run(_r())


@app.command()
def salary_advice(
    company: str = typer.Option(..., "--company"),
    title: str = typer.Option("", "--title"),
    salary: str = typer.Option("", "--salary"),
    target: str = typer.Option("", "--target"),
    strengths: str = typer.Option("", "--strengths"),
    context: str = typer.Option("", "--context"),
):
    """Get salary negotiation strategy."""
    config, _, provider = _setup()
    provider = create_provider(config)
    import asyncio

    from agent_core.pipeline.salary_advice import get_advice

    async def _r():
        r = await get_advice(config, provider, company, title, salary, target, strengths, context)
        typer.echo(f"\n锚点: {r['anchor']}")
        typer.echo(f"自信度: {r['confidence']}")
        typer.echo("筹码:")
        for line in r.get("leverage", []):
            typer.echo(f"  > {line}")
        typer.echo("让步方案:")
        for c in r.get("concessions", []):
            typer.echo(f"  - {c}")
        typer.echo("话术:")
        for s in r.get("scripts", []):
            typer.echo(f'  "{s}"')

    asyncio.run(_r())


@app.command(name="import-cookies")
def import_cookies_cmd(
    export_file: str = typer.Argument(..., help="浏览器导出的 cookie JSON 路径"),
    platform: str = typer.Argument(..., help="目标平台键，如 boss_zhipin"),
    domain: str = typer.Option("", "--domain", help="按域名子串过滤 cookie"),
):
    """Convert a browser-exported cookie JSON into the project cookie file."""
    from agent_core.platforms.cookie_utils import convert_and_save

    try:
        r = convert_and_save(export_file, platform, domain)
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"[FAIL] {e}")
        raise typer.Exit(1)
    typer.echo(f"[OK] {r['count']} cookies -> {r['out_path']}")
    if r["session_found"]:
        typer.echo(f"     session cookies: {r['session_found']}")
        typer.echo("     [OK] 登录态 cookie 存在。")
    else:
        typer.echo("     [WARN] 未发现已知 session cookie，请确认导出前已登录。")


@app.command(name="check-cookies")
def check_cookies_cmd(
    probe: bool = typer.Option(
        False, "--probe", help="实际发搜索请求探活（默认关闭，避免消耗 Boss token）"
    ),
    platform: str = typer.Option(
        "", "--platform", help="只检查指定平台，如 boss_zhipin、liepin、zhilian"
    ),
    config_path: str = typer.Option("config.yaml", "--config"),
):
    """体检各平台 cookie 健康状态（过期检查 + 重抓指引）。"""
    config, _, _ = _setup(config_path)

    import asyncio
    import warnings

    from agent_core.cookie_health import CookieStatus, check_cookies

    async def _run():
        try:
            return await check_cookies(config, probe=probe, platform_filter=platform or None)
        finally:
            # Close browser singletons so Playwright subprocess transports
            # are cleaned up before the event loop shuts down. Without this,
            # Python GC fires __del__ on unclosed pipes and spews
            # "I/O operation on closed pipe" tracebacks.
            try:
                from agent_core.platforms.zhilian_browser import close_browser as _close_zl

                await _close_zl()
            except Exception:
                pass
            try:
                from agent_core.platforms.playwright_jd import close_browser as _close_jd

                await _close_jd()
            except Exception:
                pass

    warnings.filterwarnings("ignore", message="unclosed transport")
    results = asyncio.run(_run())

    need_cookie = [r for r in results if r.needs_cookie]
    no_cookie = [r for r in results if not r.needs_cookie]
    problem = [
        r
        for r in need_cookie
        if r.status in (CookieStatus.EXPIRED, CookieStatus.MISSING, CookieStatus.EXPIRING_SOON)
    ]

    if need_cookie:
        typer.echo()
        typer.echo("═" * 56)
        typer.echo("  🔐 需要登录态的平台")
        typer.echo("─" * 56)
        for r in need_cookie:
            critical = _pick_critical_details(r.details)
            typer.echo(f"  {r.status_icon} {r.display_name:<6s}  {critical}")

        if problem:
            typer.echo()
            typer.echo("─" * 56)
            typer.echo("  ⚠️  需要重抓 cookie：")
            for r in problem:
                typer.echo(r.regrab_guide)

    if no_cookie:
        typer.echo()
        typer.echo("═" * 56)
        typer.echo("  🌐 公开 API（无需登录）")
        typer.echo("─" * 56)
        for r in no_cookie:
            typer.echo(f"  {r.status_icon} {r.display_name:<6s}  公开 API，无需 cookie")

    typer.echo()
    typer.echo("═" * 56)
    if probe:
        # Only warn about Boss token if Boss was actually probed.
        # When the user probes only Liepin/Zhilian, mentioning Boss is confusing.
        probed_boss = any(
            r.platform_key == "boss_zhipin" and r.needs_cookie and r.file_exists for r in results
        )
        if probed_boss:
            typer.echo("  探活完成。Boss token 短效，探活会消耗请求额度。")
        else:
            typer.echo("  探活完成。")
    else:
        typer.echo("  仅检查文件+过期时间，未实际探活。加 --probe 可发请求验证。")


@app.command()
def schedule(action: str = typer.Argument("status")):
    """Manage scheduled search: on, off, status."""
    config, db, provider = _setup()
    from agent_core.scheduler.scheduler import (
        acquire_lock,
        release_lock,
        schedule_off,
        schedule_on,
        schedule_status,
    )

    if action == "on":
        schedule_on(config)
        typer.echo("Scheduler ON. Run 'job-agent schedule run' to start daemon.")
    elif action == "off":
        schedule_off()
        typer.echo("Scheduler OFF")
    elif action == "run":
        schedule_on(config)
        if not acquire_lock():
            typer.echo("Another scheduler daemon is already running. Aborting.")
            return
        typer.echo(
            f"Starting daemon (every {config.schedule.interval_hours}h,"
            f" quiet {config.schedule.quiet_hours})"
        )
        typer.echo("Press Ctrl+C to stop.")
        import asyncio

        async def _daemon():
            while True:
                from agent_core.scheduler.scheduler import run_scheduled_search

                await run_scheduled_search(config, provider, db)
                await asyncio.sleep(config.schedule.interval_hours * 3600)

        try:
            asyncio.run(_daemon())
        except KeyboardInterrupt:
            typer.echo("Daemon stopped.")
        finally:
            release_lock()
    else:
        s = schedule_status()
        typer.echo(
            f"Enabled: {s['enabled']} | Runs: {s['runs']} | Last: {s.get('last_run', 'never')}"
        )
        if s.get("last_error"):
            typer.echo(f"Last error: {s['last_error']}")
        typer.echo("Commands: on | off | run | status")


@app.command()
def chat():
    """进入自然语言对话模式，LLM 自动调用工具完成任务。"""
    config, db, provider = _setup()
    _require_provider(provider, config)

    from agent_core.agent.repl import run_chat_repl

    asyncio.run(run_chat_repl(config, db, provider))


@app.command()
def cleanup(
    cache: bool = typer.Option(False, "--cache", help="清理浏览器缓存（保留登录态）"),
    logs: bool = typer.Option(False, "--logs", help="清理日志文件"),
    all_data: bool = typer.Option(False, "--all", help="清理所有数据（需重新登录）"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅显示将删除的内容，不实际删除"),
):
    """清理缓存、日志等数据文件，释放磁盘空间。"""
    import shutil
    from pathlib import Path

    data_dir = Path("data")

    items: list[tuple[str, Path]] = []

    if cache or all_data:
        for profile in ["zhilian_browser_profile", "boss_browser_profile"]:
            p = data_dir / profile
            if not p.exists():
                continue
            if all_data:
                items.append((f"浏览器 profile: {profile}", p))
            else:
                for cache_dir_name in [
                    "Cache",
                    "Code Cache",
                    "GPUCache",
                    "ShaderCache",
                    "DawnGraphiteCache",
                    "DawnWebGPUCache",
                    "GrShaderCache",
                    "GraphiteDawnCache",
                    "component_crx_cache",
                    "extensions_crx_cache",
                ]:
                    cache_dir = p / "Default" / cache_dir_name
                    if cache_dir.exists():
                        items.append((f"浏览器缓存: {cache_dir}", cache_dir))

    if logs or all_data:
        for log_file in data_dir.glob("*.log*"):
            items.append((f"日志: {log_file}", log_file))
        for log_file in data_dir.glob("**/*.log*"):
            if "zhilian_browser_profile" in str(log_file):
                items.append((f"浏览器日志: {log_file}", log_file))

    if all_data:
        db_file = data_dir / "agent.db"
        if db_file.exists():
            items.append((f"数据库: {db_file}", db_file))
        for db_extra in data_dir.glob("agent.db-*"):
            items.append((f"数据库临时文件: {db_extra}", db_extra))

    if not items:
        typer.echo("没有可清理的数据。")
        _show_disk_usage(data_dir)
        return

    total_size = 0
    for desc, path in items:
        if path.exists():
            size = (
                sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                if path.is_dir()
                else path.stat().st_size
            )
            total_size += size
            typer.echo(f"  {desc}  ({_fmt_size(size)})")

    typer.echo(f"\n  总计: {_fmt_size(total_size)}")

    if dry_run:
        typer.echo("\n[--dry-run] 未实际删除。")
        return

    typer.echo(f"\n>>> 确认删除以上 {len(items)} 项？(y/N): ", nl=False)
    try:
        if input().strip().lower() != "y":
            typer.echo("已取消。")
            return
    except (EOFError, KeyboardInterrupt):
        typer.echo("\n已取消。")
        return

    for desc, path in items:
        if not path.exists():
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            typer.echo(f"  ✅ {desc}")
        except Exception as e:
            typer.echo(f"  ❌ {desc}: {e}")

    typer.echo("\n清理完成。")
    _show_disk_usage(data_dir)


def _pick_critical_details(details: list[str]) -> str:
    """Extract cookie-expiry and probe info from details, dropping filler lines."""
    out: list[str] = []
    for d in details:
        if "共 " in d or "文件修改" in d:
            continue
        out.append(d)
    return "; ".join(out) if out else "N/A"


def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def _show_disk_usage(data_dir):
    total = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
    typer.echo(f"当前 data/ 大小: {_fmt_size(total)}")


if __name__ == "__main__":
    app()
