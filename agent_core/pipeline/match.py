"""LLM matching: deep evaluation of resume vs job requirements.

Concurrent, fault-tolerant LLM matching.
- F2: JSON enforcement + retry on parse failure; skipped count surfaced (not silent).
- F4: asyncio.gather + Semaphore concurrency.
- F7: filter results by matching.match_min_score.
- F8: tell the LLM when the JD has been truncated.
"""

import asyncio
import json
import logging
import re

from agent_core.config import load_resume

logger = logging.getLogger(__name__)

MATCH_PROMPT = (
    "You are a job matching evaluator. Score how well the resume matches this job.\n"
    "\n"
    "Resume: {resume}\n"
    "Job: {title} @ {company} | {location} | Salary: {salary}\n"
    "JD: {description}\n"
    "\n"
    "Scoring rubric:\n"
    "- 90-100: Perfect match — all required skills present, experience aligns\n"
    "- 75-89: Strong match — most key skills, minor gaps in nice-to-have areas\n"
    "- 60-74: Partial match — some key skills, 1-2 significant gaps\n"
    "- 40-59: Weak match — limited overlap, needs significant upskilling\n"
    "- 0-39: Poor match — different domain or skill level\n"
    "\n"
    "Steps: (1) Extract MUST-HAVE requirements from JD (2) Check each against resume"
    " (3) Count matches vs gaps (4) Assign score per rubric\n"
    "\n"
    "Return ONLY a JSON object (no markdown, no code blocks):\n"
    '{{"score": <0-100 int>, "match_reason": "<2-3 sentences in Chinese>",'
    ' "missing_skills": ["<skill>"], "strengths": ["<strength>"]}}\n'
)

CONCURRENCY = 5
MAX_ATTEMPTS = 2  # original + 1 retry on parse failure
JD_MAX_CHARS = 3000


async def match_jobs(prescreened, config, llm_provider):
    """Concurrent LLM matching with JSON enforcement + retry.

    Returns (results, skipped):
      - results: sorted desc by score, filtered by matching.match_min_score
      - skipped: number of jobs dropped due to LLM/parse errors (NOT threshold)
    """
    if not prescreened:
        return [], 0

    # Cache resumes (load once per resume_file)
    resume_cache = {}
    for item in prescreened:
        if item.resume_file not in resume_cache:
            try:
                resume_cache[item.resume_file] = load_resume(config, item.direction)
            except Exception as e:
                logger.error(f"Failed to load resume for {item.direction}: {e}")

    sem = asyncio.Semaphore(CONCURRENCY)

    async def _match_one(item):
        resume = resume_cache.get(item.resume_file)
        if resume is None:
            return None  # resume load failed; already logged
        job = item.job
        salary = ""
        if job.salary_min and job.salary_max:
            salary = f"{job.salary_min//1000}K-{job.salary_max//1000}K"
        elif job.salary_min:
            salary = f"{job.salary_min//1000}K+"

        # F8: truncate JD and tell the model it was cut
        desc = job.description or ""
        truncation_note = ""
        if len(desc) > JD_MAX_CHARS:
            desc = desc[:JD_MAX_CHARS]
            truncation_note = "\n(注意：JD 已截断，仅展示前部分，可能有遗漏要求)"

        prompt = MATCH_PROMPT.format(
            resume=resume,
            title=job.title,
            company=job.company,
            location=job.location,
            salary=salary,
            description=desc + truncation_note,
        )

        async with sem:
            for attempt in range(MAX_ATTEMPTS):
                try:
                    # attempt 0: enforce JSON; attempt 1: relax (in case the
                    # provider rejects response_format or still misformats)
                    rf = {"type": "json_object"} if attempt == 0 else None
                    resp = await llm_provider.chat(
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3 if attempt == 0 else 0.0,
                        max_tokens=config.llm.max_tokens,
                        response_format=rf,
                    )
                    data = _parse(resp)
                    data.update(
                        job_id=job.id,
                        job_title=job.title,
                        company=job.company,
                        direction=job.direction,
                        prescreen_score=item.score,
                        confidence=item.confidence,
                        urls=job.urls,
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
                            f"Match failed for {job.title} after {MAX_ATTEMPTS} " f"attempts: {e}"
                        )
                        return None
        return None

    raw = await asyncio.gather(*[_match_one(p) for p in prescreened])
    results = [r for r in raw if r]
    skipped = len(prescreened) - len(results)
    if skipped:
        logger.warning(f"Match: {skipped}/{len(prescreened)} jobs skipped due to LLM/parse errors")

    # F7: enforce match_min_score threshold (separate from error-skipped)
    min_score = config.matching.match_min_score
    before = len(results)
    results = [r for r in results if r.get("score", 0) >= min_score]
    filtered_out = before - len(results)
    if filtered_out:
        logger.info(f"Match: {filtered_out} jobs below min_score {min_score} filtered")

    results.sort(key=lambda r: r.get("score", 0), reverse=True)
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
