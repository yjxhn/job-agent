"""LLM matching: deep evaluation of resume vs job requirements.

Concurrent, fault-tolerant LLM matching with auditable reasoning.
- F2: JSON enforcement + retry on parse failure; skipped count surfaced (not silent).
- F4: asyncio.gather + Semaphore concurrency.
- F7: filter results by matching.match_min_score.
- F8: tell the LLM when the JD has been truncated.

2026-07-06 redesign: replaced the old "drop JD+resume → one-shot score" prompt
(which produced scores clustered at 80-95 with no auditable reasoning) with an
explicit reasoning chain. The model now MUST produce structured intermediate
artifacts (must_have / matched / gaps / evidence) before assigning a score, and
the chain-of-thought (thinking mode reasoning_content) is captured into
match_results.reasoning so every score has an audit trail.

Thinking mode is enabled via config.yaml (llm.thinking.enabled=true, effort=max)
and consumed through call_llm_with_reasoning_retry → provider.chat_with_reasoning.
"""

import asyncio
import json
import logging
import re

from agent_core.config import load_resume
from agent_core.llm.providers import call_llm_with_reasoning_retry

logger = logging.getLogger(__name__)

# Prompt version — bump when MATCH_PROMPT changes, used to tag rows in
# match_results.prompt_version so A/B comparisons across prompt revisions
# are possible.

MATCH_PROMPT = """你是一位严谨的求职匹配评估师。请按下面的步骤评估简历与岗位的匹配度，每一步都要给出明确的中间产物，不要跳步。\n\n\t{feedback}\t【简历】
    {resume}

    【岗位】{title} @ {company} | {location} | 薪资: {salary}
    【JD】（长度: {jd_length} 字{jd_completeness}）
    {description}

    【评分流程 — 必须依次执行并在 JSON 中体现】
    1. 抽取 MUST-HAVE：从 JD 中提取所有硬性要求（学历、年限、必备技能、证书、领域经验等），列成清单。若 JD 已截断，标注"（JD 截断，可能有遗漏）"。
    2. 逐条对照：对每条 MUST-HAVE，在简历中找证据。
       - 命中：把简历里的原文片段（≤30 字）作为 evidence 引用。
       - 未命中：计入 gaps，并对每个 gap 标注严重度（见下文）。
    3. 识别加分项：简历里超出 MUST-HAVE、对该岗位有价值的点，计入 strengths（每条配简历原文证据）。
       - 特别关注跨行业迁移：如果简历的行业经验与目标行业不同，但底层技能（如设备维护、PLC、故障诊断）高度通用，在 strengths 中明确标注"行业可迁移"。
    4. 缺口分级（每个 gap 必须标注严重度）：
       🔴 硬阻断：学历门槛、法定证书（电工证/注安等）、身份要求——短期内无法获取
       🟡 可弥补：特定设备经验（可入职后学习）、行业背景（底层技能通用）、软件工具——1-6 个月可补
       🟢 加分缺失：JD 里列为"优先"或"加分"的条件，不是硬性要求
    5. 缺口可闭合度：单独评估"哪些 gap 是候选人能短期内补上的"，列出 closable_gaps（可闭合的缺口清单，每条附补足方式，如"电工证：2个月可考取"）。
    6. 打分：基于"命中比例 + gaps 严重程度 + 缺口可闭合度 + 行业迁移 + 加分项质量"综合判定，参考下表：
       - 90-100：所有硬性要求全部命中，且有多项强加分项
       - 75-89：硬性要求基本命中，最多 1 个 🟡 级 gap，无 🔴
       - 60-74：核心硬性要求命中，有 🟡 级 gap 但多数可闭合，无学历/证书 🔴
       - 40-59：缺失关键证书或学历 🔴，但技能高度可迁移
       - 0-39：存在不可逾越的 🔴 级 gap（如完全不相关领域），或硬性要求大量未命中
    7. 自评置信度：若简历信息不足、JD 截断严重、或匹配维度模糊，confidence 标 low；否则按证据充分度标 high/med。

    【JD 信息不足护栏 — 必须遵守】
    - 若 MUST-HAVE 抽取数量 < 3，或 JD 长度 < 200 字，说明 JD 信息不足以支撑高匹配判断，raw_score 上限为 65，confidence 必须为 low。
    - 若 JD 长度 < 100 字（仅卡片级摘要），raw_score 上限为 50，confidence 必须为 low。
    - 这是硬约束，禁止因"无 gap 可扣"而给虚高分——信息缺失本身即证据不足。

    【输出 — 仅返回 JSON，不要 markdown 代码块，不要任何额外文字】
    {{
      "must_have": ["<硬性要求1>", "..."],
      "matched": [
        {{"requirement": "<要求>", "evidence": "<简历原文片段>"}}
      ],
      "gaps": [
        {{"gap": "<未命中的要求>", "severity": "<🔴|🟡|🟢>", "reason": "<为什么是这一级>"}}
      ],
      "closable_gaps": ["<可闭合缺口及补足方式>"],
      "strengths": ["<加分项，附简历原文证据>"],
      "industry_transfer": "<若行业不同但技能可迁移，说明具体哪些技能可迁移；否则填'无'>",
      "raw_score": <0-100 整数>,
      "confidence": "<high|med|low>",
      "match_reason": "<2-3 句中文，说明为什么是这个分，引用缺口严重度和可闭合性>"
    }}

    注意：raw_score 必须和 gaps 的数量与严重度逻辑一致，不允许"全是 🔴 级 gap 仍给 75 分"这种自相矛盾的输出。
    {truncation_note}"""

PROMPT_VERSION = "v4-gap-grading"

CONCURRENCY = 5
MAX_ATTEMPTS = 2  # original + 1 retry on parse failure
JD_MAX_CHARS = 3000

# High-score second-opinion: jobs scoring >= this threshold get a cold
# re-evaluation; if the two passes disagree by more than SCORE_DELTA_THRESHOLD,
# a third arbitration pass decides (median of three).
HIGH_SCORE_THRESHOLD = 85
SCORE_DELTA_THRESHOLD = 10

# Sentinel returned by _match_one when the resume could not be loaded —
# distinct from None (which means LLM/parse failure after MAX_ATTEMPTS)
# so the caller can split "skipped" into resume-load failures vs LLM errors.
_RESUME_MISSING = object()


async def match_jobs(jobs, config, llm_provider, on_progress=None):
    """Concurrent LLM matching with JSON enforcement + retry + reasoning capture.

    Returns (results, skipped):
      - results: sorted desc by raw_score, filtered by matching.match_min_score.
        Each item carries a "reasoning" field (the model's chain-of-thought)
        for audit/debugging.
      - skipped: number of jobs dropped due to resume-load OR LLM/parse errors
        (NOT the match_min_score threshold — those are filtered, not skipped).

    Args:
        on_progress: optional async/sync callback invoked as each job finishes
            matching (done_count, total) — used by the dashboard to render a
            live progress bar while a batch is running.
    """
    if not jobs:
        return [], 0

    # Cache resumes (load once per resume_file + direction). A load failure
    # caches None so the per-job task can drop the job and count it as
    # resume-skipped (distinct from LLM/parse-skipped) for accurate
    # diagnostics. The composite key matters: orchestrator passes an empty
    # resume_file, so keying on resume_file alone would make every direction
    # share the first direction's resume.
    resume_cache = {}
    for item in jobs:
        key = (item.resume_file, item.direction)
        if key not in resume_cache:
            try:
                resume_cache[key] = load_resume(config, item.direction)
            except Exception as e:
                logger.error(f"Failed to load resume for {item.direction}: {e}")
                resume_cache[key] = None

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _match_one(item):
        resume = resume_cache.get((item.resume_file, item.direction))
        if resume is None:
            # Resume load failed earlier (logged once at cache time).
            # Return a sentinel so the caller can distinguish resume-skips
            # from LLM/parse-skips in its accounting.
            return _RESUME_MISSING
        job = item.job
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"{job.salary_min // 1000}K-{job.salary_max // 1000}K"
        elif job.salary_min:
            salary = f"{job.salary_min // 1000}K+"

        # F8: truncate JD and tell the model it was cut
        desc = job.description or ""
        jd_length = len(desc)
        # Completeness hint: short JDs are likely card-level summaries
        # without full responsibilities/requirements — flag for the model
        # so it applies the info-deficit score guard.
        if jd_length < 100:
            jd_completeness = "，仅卡片级摘要，缺任职要求/职责正文"
        elif jd_length < 200:
            jd_completeness = "，JD 偏短，可能缺任职要求"
        else:
            jd_completeness = ""
        truncation_note = ""
        if jd_length > JD_MAX_CHARS:
            desc = desc[:JD_MAX_CHARS]
            truncation_note = "\n（注意：本 JD 已截断至前 3000 字符，可能存在未展示的硬性要求，抽取 MUST-HAVE 时请标注此不确定性，confidence 至多为 med。）"

        # Inject historical calibration feedback if any
        feedback_note = ""
        try:
            from agent_core.storage.db import get_db

            fb_conn = get_db()
            fb_rows = fb_conn.execute(
                "SELECT feedback_type, note FROM match_feedback WHERE direction=? ORDER BY created_at DESC LIMIT 5",
                (item.direction,),
            ).fetchall()
            fb_conn.close()
            if fb_rows:
                too_high = sum(1 for r in fb_rows if r[0] == "too_high")
                too_low = sum(1 for r in fb_rows if r[0] == "too_low")
                parts = []
                if too_low > 0:
                    parts.append(
                        f"历史反馈：{too_low} 次认为同类岗位评分偏低，请适当放宽匹配标准，更多关注技能可迁移性"
                    )
                if too_high > 0:
                    parts.append(
                        f"历史反馈：{too_high} 次认为同类岗位评分偏高，请更严格把关硬性门槛"
                    )
                if parts:
                    feedback_note = "【用户校准反馈 — 必须参考】\n" + "；".join(parts) + "\n\n"
        except Exception as e:
            logger.warning("match feedback load failed: %s", e)

        prompt = MATCH_PROMPT.format(
            feedback=feedback_note,
            resume=resume,
            title=job.title,
            company=job.company,
            location=job.location,
            salary=salary,
            description=desc,
            jd_length=jd_length,
            jd_completeness=jd_completeness,
            truncation_note=truncation_note,
        )

        async with sem:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    # attempt 0: enforce JSON; attempt 1: relax (in case the
                    # provider rejects response_format or still misformats).
                    # thinking mode is on via provider config (effort=max),
                    # so temperature is ignored by the API — we still pass it
                    # for the non-thinking fallback path inside chat_with_reasoning.
                    rf = {"type": "json_object"} if attempt == 0 else None
                    content, reasoning = await call_llm_with_reasoning_retry(
                        llm_provider,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3 if attempt == 0 else 0.0,
                        max_tokens=config.llm.max_tokens,
                        response_format=rf,
                    )
                    data = _parse(content)
                    data.update(
                        job_id=job.id,
                        job_title=job.title,
                        company=job.company,
                        direction=job.direction,
                        urls=job.urls,
                        reasoning=reasoning,
                        prompt_version=PROMPT_VERSION,
                    )
                    return data
                except Exception as e:
                    if attempt < MAX_ATTEMPTS - 1:
                        logger.warning(
                            f"Match parse failed for {job.title} "
                            f"(attempt {attempt + 1}/{MAX_ATTEMPTS}), retrying: {e}"
                        )
                    else:
                        logger.error(
                            f"Match failed for {job.title} after {MAX_ATTEMPTS} attempts: {e}"
                        )
                        return None
        return None

    # as_completed (not gather) so we can report per-job progress as each
    # match finishes while keeping CONCURRENCY-bounded parallelism.
    raw = []
    _total = len(jobs)
    _done = 0
    for f in asyncio.as_completed([_match_one(p) for p in jobs]):
        r = await f
        raw.append(r)
        _done += 1
        if on_progress:
            on_progress(_done, _total)
    results = [r for r in raw if r and r is not _RESUME_MISSING]
    resume_skips = sum(1 for r in raw if r is _RESUME_MISSING)
    llm_skips = sum(1 for r in raw if r is None)
    skipped = resume_skips + llm_skips
    if resume_skips:
        logger.warning(f"Match: {resume_skips}/{len(jobs)} jobs skipped (resume load failed)")
    if llm_skips:
        logger.warning(f"Match: {llm_skips}/{len(jobs)} jobs skipped (LLM/parse errors)")

    # High-score second-opinion: any raw_score >= HIGH_SCORE_THRESHOLD gets a
    # second independent evaluation at low temperature; if the two disagree by
    # more than SCORE_DELTA_THRESHOLD, run a third "arbitration" pass and take
    # the median of the three. Prevents single-pass hallucinated high scores
    # (e.g. short JD with no extractable MUST-HAVE that still scores 90+).
    high_results = [
        r for r in results if r.get("raw_score", r.get("score", 0)) >= HIGH_SCORE_THRESHOLD
    ]
    if high_results and not getattr(config.matching, "disable_second_opinion", False):
        logger.info(f"Match: second-opinion re-evaluation for {len(high_results)} high-score jobs")

        async def _re_eval(orig):
            """Re-run matching at low temperature; return new data dict or None."""
            job = orig["_job"]  # set below before gather
            resume = orig["_resume"]
            salary = orig["_salary"]
            desc = orig["_desc"]
            jd_length = orig["_jd_length"]
            jd_completeness = orig["_jd_completeness"]
            truncation_note = orig["_truncation_note"]
            prompt = MATCH_PROMPT.format(
                feedback="",
                resume=resume,
                title=job.title,
                company=job.company,
                location=job.location,
                salary=salary,
                description=desc,
                jd_length=jd_length,
                jd_completeness=jd_completeness,
                truncation_note=truncation_note,
            )
            async with sem:
                for attempt in range(MAX_ATTEMPTS):
                    try:
                        rf = {"type": "json_object"} if attempt == 0 else None
                        content, reasoning = await call_llm_with_reasoning_retry(
                            llm_provider,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.0,  # cold, deterministic
                            max_tokens=config.llm.max_tokens,
                            response_format=rf,
                        )
                        data = _parse(content)
                        data["reasoning_second"] = reasoning
                        return data
                    except Exception:
                        if attempt < MAX_ATTEMPTS - 1:
                            continue
                        return None
            return None

        # Stash context on each result for the re-eval closure.
        for r in high_results:
            item = next((p for p in jobs if p.job.id == r["job_id"]), None)
            if not item:
                continue
            r["_job"] = item.job
            r["_resume"] = resume_cache.get((item.resume_file, item.direction)) or ""
            j = item.job
            sal = ""
            if j.salary_min and j.salary_max:
                sal = f"{j.salary_min // 1000}K-{j.salary_max // 1000}K"
            elif j.salary_min:
                sal = f"{j.salary_min // 1000}K+"
            r["_salary"] = sal
            d = j.description or ""
            r["_jd_length"] = len(d)
            r["_jd_completeness"] = (
                "，仅卡片级摘要，缺任职要求/职责正文"
                if len(d) < 100
                else ("，JD 偏短，可能缺任职要求" if len(d) < 200 else "")
            )
            r["_truncation_note"] = (
                (
                    "\n（注意：本 JD 已截断至前 3000 字符，"
                    "可能存在未展示的硬性要求，抽取 MUST-HAVE 时请标注此不确定性，"
                    "confidence 至多为 med。）"
                )
                if len(d) > JD_MAX_CHARS
                else ""
            )
            r["_desc"] = d[:JD_MAX_CHARS] if len(d) > JD_MAX_CHARS else d

        re_results = await asyncio.gather(*[_re_eval(r) for r in high_results])
        arbitrated = 0
        for orig, re_eval in zip(high_results, re_results):
            if not re_eval:
                continue
            s1 = orig.get("raw_score", orig.get("score", 0))
            s2 = re_eval.get("raw_score", re_eval.get("score", 0))
            if abs(s1 - s2) > SCORE_DELTA_THRESHOLD:
                # Disagreement → third arbitration pass (already cold, but
                # take it as the decider and use the median of three).
                orig["_salary"] = orig.get("_salary", "")
                third = await _re_eval(orig)
                if third:
                    s3 = third.get("raw_score", third.get("score", 0))
                    final = sorted([s1, s2, s3])[1]  # median
                    # Adopt the third eval's structured fields (matched/gaps)
                    # if its score is the median — keeps score & rationale
                    # internally consistent.
                    if s3 == final:
                        for k in (
                            "must_have",
                            "matched",
                            "gaps",
                            "strengths",
                            "match_reason",
                            "confidence",
                        ):
                            if k in third:
                                orig[k] = third[k]
                    orig["raw_score"] = final
                    orig["second_opinion"] = {"s1": s1, "s2": s2, "s3": s3}
                    arbitrated += 1
                else:
                    # Third pass failed: take the lower of the two we have
                    # (conservative — avoid over-scoring on disagreement).
                    orig["raw_score"] = min(s1, s2)
                    orig["second_opinion"] = {"s1": s1, "s2": s2, "arbitration_failed": True}
                    arbitrated += 1
            else:
                # Agreement: keep original, but if re-eval is strictly lower
                # and within delta, prefer the more conservative (re-eval)
                # to dampen optimism bias.
                if s2 < s1:
                    orig["raw_score"] = s2
                orig["second_opinion"] = {"s1": s1, "s2": s2, "agree": True}
        if arbitrated:
            logger.info(f"Match: {arbitrated} high-score jobs needed arbitration")

    # F7: enforce match_min_score threshold (separate from error-skipped).
    # Uses raw_score from the new schema (falls back to "score" for backward compat).
    min_score = config.matching.match_min_score
    before = len(results)
    results = [r for r in results if r.get("raw_score", r.get("score", 0)) >= min_score]
    filtered_out = before - len(results)
    if filtered_out:
        logger.info(f"Match: {filtered_out} jobs below min_score {min_score} filtered")

    results.sort(key=lambda r: r.get("raw_score", r.get("score", 0)), reverse=True)
    return results, skipped


def _parse(response):
    """Extract and parse JSON from an LLM response. Raises on failure."""
    text = (response or "").strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    # Remove trailing commas before ] or } (LLM sometimes produces these)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)
