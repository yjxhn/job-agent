"""YOFC (长飞光纤) Careers adapter (yofccampus.zhiye.com) — public API, no login needed.

API discovery (2026-06-23):
  Endpoint: POST https://yofccampus.zhiye.com/api/JobAd/GetJobAdPageList
  Body: {Category, PageIndex, PageSize, KeyWords, SpecialType}
  Category ["1"] = social recruitment, ["2"] = campus recruitment.
  No PortalId or session cookie required (unlike naura which needed both).

  Response: {Code: 200, Message, Count, Data: [{Id, JobAdId, JobAdName,
    Category, LocNames, Duty, Require, ChangeDate, Salary, Degree,
    YearsOfWorking, OrgId, ...}]}
  Note: LocNames and Salary are often empty/null in the list API for
  social recruitment positions.

Known issues (2026-06-28):
  - KeyWords filter is non-functional for this tenant — any non-empty keyword
    (including exact job-title substrings) returns 0 results via the API.
  Workaround: fall back to keyword-less fetch-all + client-side substring
  filter on JobAdName / Duty / Require.

Status: Live API confirmed 2026-06-23. No cookie/auth required. 24 social + 19 campus = 43 jobs.
Platform: Beisen (北森) / zhiye.com — same API structure as NAURA.
"""

import asyncio
import hashlib
import json
import logging
import ssl
import urllib.error
import urllib.request

from agent_core.platforms.base import Job, PlatformAdapter, parse_salary_text

logger = logging.getLogger(__name__)

BASE_URL = "https://yofccampus.zhiye.com"
API_SEARCH = f"{BASE_URL}/api/JobAd/GetJobAdPageList"

_SSL_CONTEXT = ssl.create_default_context()


class YofcAdapter(PlatformAdapter):
    name = "yofc"

    def __init__(self, rate_limit_seconds: int | None = None, max_pages: int | None = None):
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 1.0
        self.max_pages = max_pages if max_pages and max_pages > 0 else 1

    async def search(
        self,
        keywords: list[str],
        location: str,
        cookie_path: str | None = None,
        headless: bool = False,
        rate_limit_seconds: int | None = None,
    ) -> list[Job]:
        """Search YOFC Careers via public POST API. No cookie required."""
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        jobs: list[Job] = []
        for keyword in keywords[:3]:
            kw_jobs = await self._search_keyword_api(keyword, location)
            jobs.extend(kw_jobs)
            if len(keywords) > 1:
                await asyncio.sleep(self._rate_limit_seconds)

        logger.info(f"[YOFC] {len(jobs)} jobs total for keywords {keywords[:3]}")
        return jobs

    def _build_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": f"{BASE_URL}/",
        }

    def _build_body(self, keyword: str, page_index: int = 0, page_size: int = 20) -> bytes:
        body = {
            "Category": ["1"],
            "PageIndex": page_index,
            "PageSize": page_size,
            "KeyWords": keyword,
            "SpecialType": 0,
        }
        return json.dumps(body).encode("utf-8")

    async def _search_keyword_api(self, keyword: str, location: str) -> list[Job]:
        """Call YOFC POST API with keyword; fall back to client-side filter if needed.

        The Beisen/zhiye.com KeyWords parameter is non-functional for this
        tenant — any non-empty keyword (even exact job-title substrings)
        returns 0 results.  When the keyword search yields nothing, we fetch
        all jobs without a keyword and filter client-side by substring match.
        """
        if not keyword:
            return []

        keyword_api_ok = False
        jobs: list[Job] = []
        for page_index in range(self.max_pages):
            try:
                req = urllib.request.Request(
                    API_SEARCH,
                    data=self._build_body(keyword, page_index=page_index),
                    headers=self._build_headers(),
                    method="POST",
                )

                def _fetch() -> bytes:
                    with urllib.request.urlopen(
                        req, timeout=20, context=_SSL_CONTEXT
                    ) as r:  # nosec B310
                        return r.read()

                raw = await asyncio.to_thread(_fetch)
                obj = json.loads(raw.decode("utf-8", "replace"))
                code = obj.get("Code")
                items = obj.get("Data", [])

                if code == 200 and items:
                    keyword_api_ok = True
                    total = obj.get("Count", 0)
                    jobs.extend(self._parse_items(items))
                    logger.info(
                        "[YOFC] keyword '%s' page %d: %d jobs (API Count=%d)",
                        keyword,
                        page_index + 1,
                        len(items),
                        total,
                    )
                    if page_index < self.max_pages - 1:
                        await asyncio.sleep(self._rate_limit_seconds)
                    continue

                logger.info(
                    "[YOFC] Keyword '%s' page %d yielded 0 API results",
                    keyword,
                    page_index + 1,
                )
                break
            except urllib.error.HTTPError as e:
                logger.info(
                    "[YOFC] Keyword API rejected '%s' (HTTP %d), "
                    "falling back to client-side filter",
                    keyword,
                    e.code,
                )
                break
            except Exception as e:
                logger.error("[YOFC] API error for '%s': %s", keyword, e)
                return jobs

        if keyword_api_ok:
            return jobs

        logger.info(
            "[YOFC] Keyword '%s' yielded 0 API results, falling back to client-side filter",
            keyword,
        )
        return await self._fetch_all_and_filter(keyword)

    async def _fetch_all_and_filter(self, keyword: str) -> list[Job]:
        """Fetch all jobs without keyword and filter client-side by substring match.

        Matches keyword against JobAdName, Duty, and Require (case-insensitive).
        YOFC has ~24 social jobs, so a single page fetch covers everything.
        """
        try:
            req = urllib.request.Request(
                API_SEARCH,
                data=self._build_body("", page_size=50),  # fetch all in one page
                headers=self._build_headers(),
                method="POST",
            )

            def _fetch() -> bytes:
                with urllib.request.urlopen(
                    req, timeout=20, context=_SSL_CONTEXT
                ) as r:  # nosec B310
                    return r.read()

            raw = await asyncio.to_thread(_fetch)
            obj = json.loads(raw.decode("utf-8", "replace"))
            items = obj.get("Data", [])
        except Exception as e:
            logger.error("[YOFC] Client-filter fetch error: %s", e)
            return []

        all_jobs = self._parse_items(items)
        kw_lower = keyword.lower()
        matched: list[Job] = []
        for job in all_jobs:
            haystack = f"{job.title}|{job.description}".lower()
            if kw_lower in haystack:
                matched.append(job)

        logger.info(
            "[YOFC] Client-side filter '%s': %d/%d jobs matched",
            keyword,
            len(matched),
            len(all_jobs),
        )
        return matched

    def _parse_items(self, items: list[dict]) -> list[Job]:
        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(self._api_item_to_job(item))
            except Exception as e:
                logger.debug("[YOFC] Skip item: %s", e)
                continue
        return jobs

    def _api_item_to_job(self, item: dict) -> Job:
        """Map one YOFC JobAd item to a Job.

        Keys: Id, JobAdId, JobAdName, Category, LocNames, Duty, Require,
        ChangeDate, Salary, Degree, YearsOfWorking, OrgId.
        """
        job_ad_id = str(item.get("JobAdId", ""))
        title = item.get("JobAdName", "")

        # LocNames is often empty for social recruitment positions
        loc_names = item.get("LocNames", [])
        if isinstance(loc_names, list) and loc_names:
            loc_name = " ".join(loc_names)
        elif isinstance(loc_names, str) and loc_names:
            loc_name = loc_names
        else:
            loc_name = ""

        # Build description
        desc_parts: list[str] = []
        category = item.get("Category", "")
        if category:
            desc_parts.append(f"类别: {category}")

        degree = item.get("Degree", "")
        if degree:
            desc_parts.append(f"学历: {degree}")
        years = item.get("YearsOfWorking", "")
        if years:
            desc_parts.append(f"经验: {years}")

        duty = item.get("Duty", "")
        if duty:
            desc_parts.append("")
            desc_parts.append("【岗位职责】")
            desc_parts.append(duty)

        require = item.get("Require", "")
        if require:
            desc_parts.append("")
            desc_parts.append("【任职要求】")
            desc_parts.append(require)

        change_date = item.get("ChangeDate", "")
        if change_date:
            desc_parts.append(f"\n更新: {change_date}")

        description = "\n".join(desc_parts)

        sal_min, sal_max = parse_salary_text(item.get("Salary", "") or "")

        # URL — same pattern as naura (Beisen/zhiye.com platform)
        item_id = item.get("Id", "")
        url = f"{BASE_URL}/campus/position/{item_id}" if item_id else ""

        fallback = f"{title}|{loc_name}" if title else job_ad_id
        unique_id = hashlib.md5(  # nosec B324 -- job ID, not security
            (f"yofc{job_ad_id or fallback}").encode()
        ).hexdigest()[:16]

        job = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": "长飞光纤",
                "location": loc_name,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "description": description,
                "url": url,
            }
        )
        job.security_id = job_ad_id
        job.lid = url  # detail URL so fetch_full_jd can actually run
        job.published_at = item.get("ChangeDate", "") or ""
        job.education = item.get("Degree", "") or ""
        return job
