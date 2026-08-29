"""Multi-platform concurrent search with cross-platform dedup."""

import asyncio
import logging
from datetime import UTC, datetime

from agent_core.platforms.base import Job

logger = logging.getLogger(__name__)

PLATFORM_ALIASES = {
    "boss": "boss_zhipin",
    "zhipin": "boss_zhipin",
    "zl": "zhilian",
    "51": "job51",
}


def resolve_platform_names(config, names) -> tuple[list[str], list[str]]:
    """Normalize CLI platform aliases and split known/unknown names.

    Returns (known_names, unknown_names). Known names keep their original
    order and are deduplicated.
    """
    known: list[str] = []
    unknown: list[str] = []
    for raw in names or []:
        name = (raw or "").strip()
        if not name:
            continue
        mapped = PLATFORM_ALIASES.get(name, name)
        if mapped in config.platforms:
            if mapped not in known:
                known.append(mapped)
        else:
            unknown.append(name)
    return known, unknown


def _make_job_id(platform: str, url: str) -> str:
    from agent_core.platforms.registry import make_job_id

    return make_job_id(platform, url)


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
        (canonical, v.lower()) for canonical, variants in aliases.items() for v in variants
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


def _record_status(sink, platform, direction, status, result_count=0, error=""):
    """Append one per-platform search result to an optional status sink."""
    if sink is None:
        return
    sink.append(
        {
            "platform": platform,
            "direction": direction,
            "status": status,
            "result_count": result_count,
            "error_message": error,
        }
    )


async def search_all(
    config,
    platform_names=None,
    directions=None,
    keywords=None,
    headless=False,
    max_pages=None,
    status_sink=None,
) -> list[Job]:
    """Search across platforms x directions.

    Args:
        keywords: Explicit search keywords. When provided, these are used for ALL
            directions instead of config.directions[d].keywords. When None,
            config keywords are used as a fallback — but if the direction has no
            config keywords either, it is skipped with a warning.
        max_pages: Optional CLI override for per-platform page count. None means
            use each platform's config search_max_pages.
        status_sink: Optional list that receives per-platform result metadata.
    """
    if platform_names is None:
        platform_names = [n for n, p in config.platforms.items() if p.enabled]
    else:
        platform_names, unknown = resolve_platform_names(config, platform_names)
        if unknown:
            logger.warning(f"Ignoring unknown platform keys: {unknown}")
    if directions is None:
        directions = list(config.directions.keys())

    all_jobs: list[Job] = []
    tasks = []
    keyword_map: dict[str, list[str]] = {}
    _now = datetime.now(UTC)

    # Global concurrency cap for platform searches. 8 platforms × N directions
    # can otherwise hammer sites/TLS simultaneously; 4 keeps real-world runs
    # fast while reducing transient connection failures.
    _search_sem = asyncio.Semaphore(4)

    async def _limited(
        pname,
        pc,
        kws,
        loc,
        dname,
        headless,
        max_pages,
        status_sink,
    ):
        async with _search_sem:
            return await _search_one(
                pname,
                pc,
                kws,
                loc,
                dname,
                headless,
                max_pages=max_pages,
                status_sink=status_sink,
            )

    # When explicit keywords are provided, search once per platform (not per direction).
    # A single --direction still acts as the label for the stored jobs.
    if keywords:
        direction_label = directions[0] if directions else "user_query"
        keyword_map = {direction_label: keywords}
        for pname in platform_names:
            if pname not in config.platforms or not config.platforms[pname].enabled:
                continue
            tasks.append(
                _limited(
                    pname,
                    config.platforms[pname],
                    keywords,
                    config.search_location,
                    direction_label,
                    headless,
                    max_pages,
                    status_sink,
                )
            )
    else:
        for dname in directions:
            if dname not in config.directions:
                continue
            kw = config.directions[dname].keywords
            if not kw:
                logger.warning(
                    f"Direction '{dname}': no keywords provided and no defaults configured. "
                    f"Pass --keyword or set keywords in config. Skipping."
                )
                continue
            keyword_map[dname] = kw
            for pname in platform_names:
                if pname not in config.platforms or not config.platforms[pname].enabled:
                    continue
                tasks.append(
                    _limited(
                        pname,
                        config.platforms[pname],
                        kw,
                        config.search_location,
                        dname,
                        headless,
                        max_pages,
                        status_sink,
                    )
                )

    if not tasks:
        logger.warning("No platform+keyword combinations to search")
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Search task failed: {result}")
        elif result:
            all_jobs.extend(result)  # type: ignore[arg-type]

    # Shared relevance guard: drop platform results that have nothing to do
    # with the requested keywords (e.g. Zhilian promoted/generic listings).
    if all_jobs:
        if keywords:
            all_jobs = filter_by_keywords(all_jobs, keywords)
        else:
            kept: list[Job] = []
            for j in all_jobs:
                kws = keyword_map.get(j.direction)
                if not kws or filter_by_keywords([j], kws):
                    kept.append(j)
            all_jobs = kept

    return _dedup(all_jobs, config.company_aliases)


async def _search_one(
    pname, pc, keywords, location, dname, headless=False, max_pages=None, status_sink=None
) -> list[Job]:
    """Search one platform for one direction using real adapter."""
    logger.info(f"[{pname}] Searching {dname}: {keywords}")
    eff_max_pages = max_pages if max_pages is not None else getattr(pc, "search_max_pages", 1)
    try:
        if pname == "company_site":
            from agent_core.platforms.company_site import COMPANY_SITES, CompanySiteAdapter

            all_jobs = []
            site_error = ""
            for ckey in COMPANY_SITES:
                try:
                    adapter = CompanySiteAdapter(ckey)  # type: ignore[assignment]
                    cjobs = await adapter.search(
                        keywords=keywords, location=location, headless=headless
                    )
                    all_jobs.extend(cjobs)
                except NotImplementedError:
                    logger.debug(f"[company_site] {ckey}: not yet implemented")
                    site_error = f"{ckey}: not implemented"
                except Exception as e:
                    logger.error(f"[company_site] {ckey} error: {e}")
                    site_error = f"{ckey}: {e}"
            _record_status(
                status_sink,
                pname,
                dname,
                "success" if all_jobs else "no_results",
                len(all_jobs),
                site_error,
            )
            return all_jobs

        from agent_core.platforms.registry import create_adapter, is_registered

        if not is_registered(pname):
            logger.warning(f"[{pname}] Adapter not implemented — returning empty")
            _record_status(status_sink, pname, dname, "no_results", 0, "adapter not implemented")
            return []
        platform_adapter = create_adapter(pname, pc, eff_max_pages)

        jobs = await platform_adapter.search(
            keywords=keywords,
            location=location,
            cookie_path=pc.cookie_path,
            headless=headless,
            rate_limit_seconds=pc.rate_limit_seconds,
        )
        # Tag jobs with direction and discovery timestamp
        now = datetime.now(UTC)
        for j in jobs:
            j.direction = dname
            if not j.first_seen:
                j.first_seen = now
            j.last_seen = now
        _record_status(status_sink, pname, dname, "success" if jobs else "no_results", len(jobs))
        return jobs
    except NotImplementedError:
        logger.warning(f"[{pname}] Not yet implemented")
        _record_status(status_sink, pname, dname, "no_results", 0, "not implemented")
        return []
    except Exception as e:
        logger.error(f"[{pname}] Search error: {e}")
        _record_status(status_sink, pname, dname, "error", 0, str(e))
        return []


def filter_by_company(jobs: list[Job], company: str) -> list[Job]:
    """Filter jobs by company name (case-insensitive substring match).

    Checks both ``job.company`` and ``job.company_normalized``.
    Returns filtered list.
    """
    if not company:
        return jobs
    q = company.lower().strip()
    return [
        j
        for j in jobs
        if q in (j.company or "").lower() or q in (j.company_normalized or "").lower()
    ]


def _keyword_matches(keyword: str, title: str) -> bool:
    """True when a job title is meaningfully related to one search keyword.

    English/ASCII keywords require the full keyword substring in the title.
    Chinese keywords either contain the full keyword or share at least 2/3 of
    the keyword's CJK characters — strong enough to drop generic/promoted
    listings while keeping paraphrased real titles.
    """
    kw = keyword.strip().lower()
    if not kw:
        return False
    title_l = (title or "").lower()
    if kw in title_l:
        return True
    cjk = [c for c in kw if "\u4e00" <= c <= "\u9fff"]
    if cjk:
        kw_chars = set(cjk)
        overlap = kw_chars & set(title_l)
        return len(overlap) / len(kw_chars) >= 2 / 3
    return False


def filter_by_keywords(jobs: list[Job], keywords: list[str]) -> list[Job]:
    """Drop jobs unrelated to all requested keywords (shared relevance guard)."""
    kws = [k.strip().lower() for k in (keywords or []) if k and k.strip()]
    if not kws:
        return list(jobs)
    return [j for j in jobs if any(_keyword_matches(k, j.title or "") for k in kws)]


_TITLE_FUZZ_THRESHOLD = 0.85  # titles within this similarity merge when company matches


def _prefer_richer_description(new: str, old: str) -> bool:
    """True when the new description carries more information than the old."""
    if not new:
        return False
    if not old:
        return True
    jd_markers = ("JD:", "岗位职责", "任职要求", "职位描述", "工作内容", "工作职责")
    new_has_jd = any(m in new for m in jd_markers)
    old_has_jd = any(m in old for m in jd_markers)
    if new_has_jd and not old_has_jd:
        return True
    if old_has_jd and not new_has_jd:
        return False
    return len(new) > len(old)


def _dedup(jobs: list[Job], aliases: dict) -> list[Job]:
    for j in jobs:
        j.company_normalized = _normalize_company(j.company, aliases)

    seen: dict[str, Job] = {}
    seen_norm: list[tuple[str, Job]] = []  # (dedup_key, job) for fuzzy matching
    for j in jobs:
        key = j.dedup_key()
        existing = seen.get(key)
        if existing is None:
            # Same company, fuzzy title match — e.g. "AMR工程师" vs "AMR调度工程师"
            existing = _fuzzy_title_match(j, seen_norm)
        if existing is None:
            seen[key] = j
            seen_norm.append((key, j))
            continue

        existing.platforms = list(set(existing.platforms + j.platforms))
        existing.urls.update(j.urls)
        if j.last_seen and (not existing.last_seen or j.last_seen > existing.last_seen):
            existing.last_seen = j.last_seen
        existing.is_new = existing.is_new or j.is_new
        # Merge the most informative copy of each field instead of blindly
        # keeping whichever platform happened to be searched first.
        if existing.salary_min is None and j.salary_min is not None:
            existing.salary_min = j.salary_min
        if existing.salary_max is None and j.salary_max is not None:
            existing.salary_max = j.salary_max
        if _prefer_richer_description(j.description or "", existing.description or ""):
            existing.description = j.description
        if not existing.location and j.location:
            existing.location = j.location
        if not existing.education and j.education:
            existing.education = j.education
        if not existing.published_at and j.published_at:
            existing.published_at = j.published_at
        if not existing.security_id and j.security_id:
            existing.security_id = j.security_id
        if not existing.lid and j.lid:
            existing.lid = j.lid
        if not existing.direction and j.direction:
            existing.direction = j.direction
        if not existing.company and j.company:
            existing.company = j.company
    return list(seen.values())


def _fuzzy_title_match(job: Job, seen_norm: list[tuple[str, Job]]) -> Job | None:
    """Return the job in seen whose dedup_key matches job's fuzzily (same company).

    Only compares against keys with the same company_normalized; title similarity
    must be >= _TITLE_FUZZ_THRESHOLD. Long titles are compared on a shared
    substring window to avoid one huge role shadowing a short one.
    """
    from difflib import SequenceMatcher

    key = job.dedup_key()
    if not key:
        return None
    company, _, title = key.partition("|")
    if not title:
        return None
    for k, existing in seen_norm:
        ec, _, etitle = k.partition("|")
        if ec != company or not etitle:
            continue
        ratio = SequenceMatcher(None, title, etitle).ratio()
        if ratio >= _TITLE_FUZZ_THRESHOLD:
            return existing
    return None
