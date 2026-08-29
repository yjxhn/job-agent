"""Job enrichment utilities for on-demand JD fetching."""

import logging

from agent_core.platforms.base import Job

logger = logging.getLogger(__name__)


async def enrich_job_jd(job: Job, config) -> Job:
    """Enrich a job's description with full JD text on-demand.

    This function fetches the complete job description from the platform's
    detail endpoint when needed (e.g., for match/tailor/cover-letter commands),
    avoiding anti-bot triggers during bulk search operations.

    Args:
        job: Job object with security_id/lid fields populated
        config: Config object with platform configurations

    Returns:
        Job object with potentially enriched description (same object reference)
    """
    # Universal short-circuit: if the description already contains real JD
    # content (from search API or a prior fetch), don't waste requests.
    desc = job.description or ""
    if any(kw in desc for kw in ("岗位职责", "任职要求", "职位描述", "工作内容", "工作职责")):
        logger.debug(f"[Enrich] Job {job.id[:8]} already has JD, skipping")
        return job

    if not job.security_id and not job.lid:
        logger.debug(f"[Enrich] No security_id/lid for job {job.id}, skipping enrichment")
        return job

    # Determine platform from job.urls or job.platforms
    platform = None
    if job.urls:
        platform = list(job.urls.keys())[0]
    elif job.platforms:
        platform = job.platforms[0]

    if not platform or platform not in config.platforms:
        logger.debug(f"[Enrich] Unknown or disabled platform for job {job.id}: {platform}")
        return job

    platform_config = config.platforms[platform]
    if not platform_config.enabled:
        logger.debug(f"[Enrich] Platform {platform} not enabled, skipping enrichment")
        return job

    try:
        from agent_core.platforms.registry import create_adapter, is_registered

        if not is_registered(platform):
            logger.warning(f"[Enrich] No fetch_full_jd implementation for platform {platform}")
            return job
        # fetch_full_jd only needs the adapter's default profile/cookie wiring;
        # passing platform_config would force constructor kwargs that some
        # tests/legacy paths stub away.
        adapter = create_adapter(platform)

        # Fetch full JD
        full_jd = await adapter.fetch_full_jd(job, platform_config.cookie_path)
        if full_jd:
            # Prepend JD to existing description
            job.description = f"JD: {full_jd}\n\n{job.description}"
            logger.info(f"[Enrich] Enriched job {job.id} with JD (len={len(full_jd)})")
        else:
            logger.debug(f"[Enrich] No JD fetched for job {job.id}")
    except Exception as e:
        logger.warning(f"[Enrich] Failed to enrich job {job.id}: {e}")

    return job
