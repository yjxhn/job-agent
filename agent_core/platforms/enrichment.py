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
        # Import the adapter dynamically
        if platform == "boss_zhipin":
            from agent_core.platforms.boss_zhipin import BossZhipinAdapter
            adapter = BossZhipinAdapter()
        elif platform == "liepin":
            from agent_core.platforms.liepin import LiepinAdapter
            adapter = LiepinAdapter()  # type: ignore[assignment]
        else:
            logger.warning(f"[Enrich] No fetch_full_jd implementation for platform {platform}")
            return job

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