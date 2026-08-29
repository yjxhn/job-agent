"""Tencent Careers adapter (careers.tencent.com) — public API, no login needed.

API discovery (2026-06-21):
  Endpoint: GET https://careers.tencent.com/tencentcareer/api/post/Query
  Params: timestamp, keyword, pageIndex, pageSize, language, area,
    parentCategoryId (optional), cityId (optional), bgIds (optional)
  Response: {Code, Data: {Count, Posts: [{PostId, RecruitPostName,
    LocationName, CountryName, BGName, CategoryName, Responsibility,
    LastUpdateTime, PostURL, RecruitPostId, RequireWorkYearsName}]}}
  No salary in list response — available only on detail page (not fetched).

Status: Live API confirmed 2026-06-21. No cookie/auth required.
"""

import asyncio
import hashlib
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://careers.tencent.com"
API_SEARCH = f"{BASE_URL}/tencentcareer/api/post/Query"
JOB_URL_PREFIX = "http://careers.tencent.com/jobdesc.html?postId="


class TencentAdapter(PlatformAdapter):
    name = "tencent"

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
        """Search Tencent Careers via public GET API. No cookie required."""
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        jobs: list[Job] = []
        for keyword in keywords[:3]:
            kw_jobs = await self._search_keyword_api(keyword, location)
            jobs.extend(kw_jobs)
            if len(keywords) > 1:
                await asyncio.sleep(self._rate_limit_seconds)

        logger.info(f"[Tencent] {len(jobs)} jobs total for keywords {keywords[:3]}")
        return jobs

    async def _search_keyword_api(self, keyword: str, location: str) -> list[Job]:
        """Call Tencent GET /tencentcareer/api/post/Query with paging."""
        jobs: list[Job] = []
        for page_index in range(1, self.max_pages + 1):
            ts = int(time.time() * 1000)
            params = {
                "timestamp": ts,
                "keyword": keyword,
                "pageIndex": page_index,
                "pageSize": 20,
                "language": "zh-cn",
                "area": "cn",
            }

            qs = urllib.parse.urlencode(params)
            url = f"{API_SEARCH}?{qs}"

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"{BASE_URL}/",
                },
            )

            def _fetch() -> bytes:
                with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                    return r.read()

            try:
                raw = await asyncio.to_thread(_fetch)
                import json

                obj = json.loads(raw.decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                logger.error(f"[Tencent] HTTP {e.code} for '{keyword}': {e.reason}")
                return jobs
            except Exception as e:
                logger.error(f"[Tencent] API error for '{keyword}': {e}")
                return jobs

            code = obj.get("Code")
            data = obj.get("Data", {})
            posts = data.get("Posts") or []
            total = data.get("Count", 0)

            if code != 200:
                logger.warning(f"[Tencent] API code={code} for '{keyword}'")
                return jobs

            for post in posts:
                try:
                    jobs.append(self._api_item_to_job(post))
                except Exception as e:
                    logger.debug(f"[Tencent] Skip post: {e}")
                    continue

            logger.info(
                f"[Tencent] '{keyword}' page {page_index}: " f"{len(posts)} jobs (total={total})"
            )
            if not posts or page_index >= self.max_pages:
                break
            await asyncio.sleep(self._rate_limit_seconds)

        return jobs

    def _api_item_to_job(self, item: dict) -> Job:
        """Map one Tencent Post to a Job.

        Keys: PostId, RecruitPostName, CountryName, LocationName, BGName,
        CategoryName, Responsibility, LastUpdateTime, PostURL, RecruitPostId,
        RequireWorkYearsName, ProductName, ComName.
        """
        post_id = str(item.get("PostId", ""))
        title = item.get("RecruitPostName", "")
        country = item.get("CountryName", "")
        city = item.get("LocationName", "")
        location = city if country == "中国" else f"{country} {city}".strip() if country else city

        # Tencent list API doesn't include salary; set to None
        bg = item.get("BGName", "")
        category = item.get("CategoryName", "")

        # Build description
        desc_parts: list[str] = []
        if bg:
            desc_parts.append(f"BG: {bg}")
        if category:
            desc_parts.append(f"类别: {category}")
        years = item.get("RequireWorkYearsName", "")
        if years:
            desc_parts.append(f"经验: {years}")
        resp = item.get("Responsibility", "")
        if resp:
            desc_parts.append(resp)

        description = "\n".join(desc_parts)

        # URL: prefer PostURL, fallback to constructed
        url = item.get("PostURL", "")
        if not url:
            url = f"{JOB_URL_PREFIX}{post_id}"

        unique_id = hashlib.md5((post_id or f"tencent{title}").encode()).hexdigest()[  # nosec B324
            :16
        ]

        job = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": "腾讯",
                "location": location,
                "salary_min": None,
                "salary_max": None,
                "description": description,
                "url": url,
            }
        )
        job.security_id = post_id
        job.lid = url  # detail URL so fetch_full_jd can actually run
        job.published_at = item.get("LastUpdateTime", "") or ""
        return job
