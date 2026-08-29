"""NetEase HR adapter (hr.163.com) — public API, no login needed.

API discovery (2026-06-21):
  Endpoint: POST https://hr.163.com/api/hr163/position/queryPage
  Body: {currentPage, pageSize, keyword}
  Response: {code, data: {total, pages, lastPage, list: [{id, name,
    workType, firstPostTypeName, recruitNum, requirement, description,
    reqEducationName, reqWorkYearsName, firstDepName, workPlaceNameList,
    productName, updateTime, beeUrl}]}}
  No salary in list response.

Status: Live API confirmed 2026-06-21. No cookie/auth required.
"""

import asyncio
import hashlib
import json
import logging
import urllib.error
import urllib.request

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

API_SEARCH = "https://hr.163.com/api/hr163/position/queryPage"
# NetEase workPlaceList uses numeric codes, but workPlaceNameList has names
# workType: "0"=full-time, "1"=intern?, etc.


class NeteaseAdapter(PlatformAdapter):
    name = "netease"

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
        """Search NetEase HR via public POST API. No cookie required."""
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        jobs: list[Job] = []
        for keyword in keywords[:3]:
            kw_jobs = await self._search_keyword_api(keyword, location)
            jobs.extend(kw_jobs)
            if len(keywords) > 1:
                await asyncio.sleep(self._rate_limit_seconds)

        logger.info(f"[NetEase] {len(jobs)} jobs total for keywords {keywords[:3]}")
        return jobs

    async def _search_keyword_api(self, keyword: str, location: str) -> list[Job]:
        """Call NetEase POST /api/hr163/position/queryPage with paging."""
        jobs: list[Job] = []
        for current_page in range(1, self.max_pages + 1):
            body = {
                "currentPage": current_page,
                "pageSize": 20,
                "keyword": keyword,
            }
            body_bytes = json.dumps(body).encode("utf-8")

            req = urllib.request.Request(
                API_SEARCH,
                data=body_bytes,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Referer": "https://hr.163.com/",
                    "Origin": "https://hr.163.com",
                },
                method="POST",
            )

            def _fetch() -> bytes:
                with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                    return r.read()

            try:
                raw = await asyncio.to_thread(_fetch)
                obj = json.loads(raw.decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                logger.error(f"[NetEase] HTTP {e.code} for '{keyword}': {e.reason}")
                return jobs
            except Exception as e:
                logger.error(f"[NetEase] API error for '{keyword}': {e}")
                return jobs

            code = obj.get("code")
            data = obj.get("data", {})
            items = data.get("list", [])
            total = data.get("total", 0)

            if code != 200:
                logger.warning(f"[NetEase] API code={code} for '{keyword}'")
                return jobs

            for item in items:
                try:
                    jobs.append(self._api_item_to_job(item))
                except Exception as e:
                    logger.debug(f"[NetEase] Skip item: {e}")
                    continue

            logger.info(
                f"[NetEase] '{keyword}' page {current_page}: " f"{len(items)} jobs (total={total})"
            )
            if not items or current_page >= self.max_pages:
                break
            await asyncio.sleep(self._rate_limit_seconds)

        return jobs

    def _api_item_to_job(self, item: dict) -> Job:
        """Map one NetEase position list item to a Job.

        Keys: id, name, workType, firstPostTypeName, recruitNum, requirement,
        description, reqEducationName, reqWorkYearsName, firstDepName,
        workPlaceNameList, updateTime, product, productName, beeUrl.
        """
        item_id = str(item.get("id", ""))
        title = item.get("name", "")
        department = item.get("firstDepName", "")

        # Location: workPlaceNameList is a list of city names
        location_parts = item.get("workPlaceNameList", [])
        if isinstance(location_parts, list) and location_parts:
            location = " ".join(location_parts)
        else:
            location = ""

        # NetEase list API doesn't include salary
        desc_parts: list[str] = []
        edu = item.get("reqEducationName", "")
        if edu and edu != "不限":
            desc_parts.append(f"学历: {edu}")
        exp = item.get("reqWorkYearsName", "")
        if exp and exp != "不限":
            desc_parts.append(f"经验: {exp}")
        post_type = item.get("firstPostTypeName", "")
        if post_type:
            desc_parts.append(f"类型: {post_type}")
        if department:
            desc_parts.append(f"部门: {department}")
        prod = item.get("productName", "")
        if prod:
            desc_parts.append(f"产品: {prod}")
        num = item.get("recruitNum", 0)
        if num:
            desc_parts.append(f"招聘人数: {num}")

        # Full description
        desc = item.get("description", "")
        if desc:
            desc_parts.append("")
            desc_parts.append(desc)

        description = "\n".join(desc_parts)

        # URL
        bee_url = item.get("beeUrl")
        if bee_url:
            url = bee_url
        else:
            url = f"https://hr.163.com/job-detail.html?id={item_id}"

        fallback = f"{title}|{location}" if title else item_id
        unique_id = hashlib.md5(  # nosec B324 -- job ID, not security
            (f"netease{item_id or fallback}").encode()
        ).hexdigest()[:16]

        job = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": "网易",
                "location": location,
                "salary_min": None,
                "salary_max": None,
                "description": description,
                "url": url,
            }
        )
        job.security_id = item_id
        job.lid = url  # detail URL so fetch_full_jd can actually run
        job.published_at = item.get("updateTime", "") or ""
        job.education = item.get("reqEducationName", "") or ""
        return job
