"""Pipeline orchestrator: tie stages together, support partial runs."""

import logging

from agent_core.pipeline import filter as filter_mod
from agent_core.pipeline import match, prescreen, search

logger = logging.getLogger(__name__)
STAGE_ORDER = ["search", "filter", "enrich", "prescreen", "match"]


async def run_pipeline(
    config,
    llm_provider,
    stages=None,
    keywords=None,
    directions=None,
    platforms=None,
    headless=False,
):
    if stages is None:
        stages = STAGE_ORDER
    stage_set = set(stages)
    data = {"jobs": [], "filtered": [], "prescreened": [], "matched": []}

    if "search" in stage_set:
        jobs = await search.search_all(config, platforms, directions, headless=headless)
        data["jobs"] = jobs
        logger.info(f"Search: {len(jobs)} jobs after dedup")

    if "filter" in stage_set:
        filtered = filter_mod.filter_jobs(data["jobs"] or [], config)
        data["filtered"] = filtered

    if "enrich" in stage_set and config.matching.enrich_in_pipeline:
        from agent_core.platforms.enrichment import enrich_job_jd

        source = data.get("filtered") or data.get("jobs") or []
        # Sort by salary_max desc (best guess for "top" jobs) to pick top-N
        top = sorted(source, key=lambda j: j.salary_max or 0, reverse=True)[
            : config.matching.enrich_top_n
        ]
        enriched_count = 0
        for j in top:
            try:
                await enrich_job_jd(j, config)
                enriched_count += 1
            except Exception as e:
                logger.warning(f"Enrich failed for {j.id} ({j.title}): {e}")
        logger.info(f"Enrichment: {enriched_count}/{len(top)} jobs enriched")
        data["enriched"] = enriched_count

    if "prescreen" in stage_set:
        ps = prescreen.prescreen(data["filtered"] or data["jobs"] or [], config)
        data["prescreened"] = ps
        logger.info(f"Prescreen: {len(ps)} items for LLM matching")
        for p in ps:
            logger.info(f"  {p.score:.0f}% [{p.confidence}] {p.job.title} @ {p.job.company}")

    if "match" in stage_set:
        matched, skipped = await match.match_jobs(data["prescreened"] or [], config, llm_provider)
        data["matched"] = matched
        data["skipped"] = skipped
        logger.info(f"Match: {len(matched)} results (skipped {skipped} on error)")
        for m in matched:
            logger.info(
                f"  {m.get('score','?')}% {m.get('job_title','?')} @ {m.get('company','?')}"
            )

    # Toast notification after pipeline completes
    try:
        from agent_core.notify.windows_toast import notify_search_complete

        total = len(data.get("matched", []) or data.get("prescreened", []) or data.get("jobs", []))
        notify_search_complete(total, data.get("skipped", 0))
    except Exception as e:
        logger.debug(f"Toast notify skipped: {e}")

    return data
