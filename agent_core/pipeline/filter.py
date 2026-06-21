"""Rule-based filtering: salary, location, keywords, exclude terms."""

import logging

from agent_core.platforms.base import Job

logger = logging.getLogger(__name__)


def filter_jobs(jobs: list[Job], config) -> list[Job]:
    result = []
    for job in jobs:
        if _passes(job, config):
            result.append(job)
    logger.info(f"Filter: {len(jobs)} in -> {len(result)} out")
    return result


def _passes(job: Job, config) -> bool:
    for kw in config.exclude_keywords:
        if kw in job.title or kw in job.description:
            logger.debug(f"Excluded ({kw}): {job.title}")
            return False
    if job.salary_max is not None and job.salary_max < config.min_salary:
        return False
    if config.search_location and config.search_location != "全国":
        if config.search_location not in job.location:
            return False
    return True
