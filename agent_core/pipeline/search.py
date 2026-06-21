"""Multi-platform concurrent search with cross-platform dedup."""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime

from agent_core.platforms.base import Job

logger = logging.getLogger(__name__)


def _make_job_id(platform: str, url: str) -> str:
    return hashlib.md5(f"{platform}:{url}".encode()).hexdigest()[:16]  # nosec B324 -- job ID, not security


def _normalize_company(name: str, aliases: dict) -> str:
    """Normalize company name using alias table first, then fuzzy matching."""
    from difflib import SequenceMatcher
    name_lower = name.strip().lower()
    # 1) Exact match in alias table
    for canonical, variants in aliases.items():
        for v in variants:
            if name_lower == v.lower() or name_lower in v.lower() or v.lower() in name_lower:
                return canonical
    # 2) Fuzzy match against all known names
    all_known = [
        (canonical, v.lower())
        for canonical, variants in aliases.items()
        for v in variants
    ]
    best_score: float = 0.0
    best_canonical = name.strip()
    for canonical, v_lower in all_known:
        score = SequenceMatcher(None, name_lower, v_lower).ratio()
        if score > best_score:
            best_score = score
            best_canonical = canonical
    if best_score >= 0.75:
        return best_canonical
    return name.strip()


async def search_all(config, platform_names=None, directions=None, headless=False) -> list[Job]:
    if platform_names is None:
        platform_names = [n for n, p in config.platforms.items() if p.enabled]
    if directions is None:
        directions = list(config.directions.keys())

    all_jobs: list[Job] = []
    tasks = []
    _now = datetime.now(UTC)

    for dname in directions:
        if dname not in config.directions:
            continue
        kw = config.directions[dname].keywords
        for pname in platform_names:
            if pname not in config.platforms or not config.platforms[pname].enabled:
                continue
            tasks.append(_search_one(pname, config.platforms[pname], kw,
                                    config.search_location, dname, headless))

    if not tasks:
        logger.warning("No platform+keyword combinations to search")
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Search task failed: {result}")
        elif result:
            all_jobs.extend(result)  # type: ignore[arg-type]

    return _dedup(all_jobs, config.company_aliases)


async def _search_one(pname, pc, keywords, location, dname, headless=False) -> list[Job]:
    """Search one platform for one direction using real adapter."""
    logger.info(f"[{pname}] Searching {dname}: {keywords}")
    try:
        if pname == "boss_zhipin":
            from agent_core.platforms.boss_zhipin import BossZhipinAdapter
            adapter = BossZhipinAdapter()
        elif pname == "liepin":
            from agent_core.platforms.liepin import LiepinAdapter
            adapter = LiepinAdapter()  # type: ignore[assignment]
        elif pname == "company_site":
            from agent_core.platforms.company_site import COMPANY_SITES, CompanySiteAdapter
            # Try each known company site
            all_jobs = []
            for ckey in COMPANY_SITES:
                try:
                    adapter = CompanySiteAdapter(ckey)  # type: ignore[assignment]
                    cjobs = await adapter.search(keywords=keywords, location=location,
                                                 headless=headless)
                    all_jobs.extend(cjobs)
                except NotImplementedError:
                    logger.debug(f"[company_site] {ckey}: not yet implemented")
                except Exception as e:
                    logger.error(f"[company_site] {ckey} error: {e}")
            return all_jobs
        else:
            logger.warning(f"[{pname}] Adapter not implemented — returning empty")
            return []

        jobs = await adapter.search(
            keywords=keywords,
            location=location,
            cookie_path=pc.cookie_path,
            headless=headless,
            rate_limit_seconds=pc.rate_limit_seconds,
        )
        # Adapter handles its own per-request rate limiting
        # Tag jobs with direction
        for j in jobs:
            j.direction = dname
        return jobs
    except NotImplementedError:
        logger.warning(f"[{pname}] Not yet implemented")
        return []
    except Exception as e:
        logger.error(f"[{pname}] Search error: {e}")
        return []


def _dedup(jobs: list[Job], aliases: dict) -> list[Job]:
    for j in jobs:
        j.company_normalized = _normalize_company(j.company, aliases)

    seen: dict[str, Job] = {}
    for j in jobs:
        key = j.dedup_key()
        if key in seen:
            existing = seen[key]
            existing.platforms = list(set(existing.platforms + j.platforms))
            existing.urls.update(j.urls)
            if j.last_seen and (not existing.last_seen or j.last_seen > existing.last_seen):
                existing.last_seen = j.last_seen
            existing.is_new = existing.is_new or j.is_new
        else:
            seen[key] = j
    return list(seen.values())
