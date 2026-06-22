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


def _parse_salary_netease(text: str) -> tuple[int | None, int | None]:
    """Parse NetEase salary strings. NetEase list API doesn't include salary,
    so this is for future detail-page parsing."""
    if not text:
        return None, None
    return _parse_salary(text)


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Parse salary string into (min, max) in yuan. Same pattern as zhilian."""
    import re

    if not text:
        return None, None
    text = text.strip()

    if "年薪" in text:
        m = re.findall(r"(\d+(?:\.\d+)?)", text)
        if m:
            amt = float(m[0]) * 10000
            return int(amt // 13), int(amt // 12)

    if "万" in text or "千" in text:
        nums = re.findall(r"(\d+(?:\.\d+)?)", text)
        multipliers: list[float] = []
        for part in re.split(r"[-~]", text):
            if "万" in part:
                n = re.search(r"(\d+(?:\.\d+)?)", part)
                if n:
                    multipliers.append(float(n.group(1)) * 10000)
            elif "千" in part:
                n = re.search(r"(\d+(?:\.\d+)?)", part)
                if n:
                    multipliers.append(float(n.group(1)) * 1000)
        if len(multipliers) >= 2:
            return int(multipliers[0]), int(multipliers[1])
        if len(multipliers) == 1:
            return int(multipliers[0]), None
        return None, None

    if "K" in text or "k" in text:
        nums = re.findall(r"(\d+(?:\.\d+)?)", text)
        if len(nums) >= 2:
            return int(float(nums[0]) * 1000), int(float(nums[1]) * 1000)
        if len(nums) == 1:
            return int(float(nums[0]) * 1000), None
        return None, None

    nums = re.findall(r"(\d+)", text)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        return int(nums[0]), None
    return None, None


class NeteaseAdapter(PlatformAdapter):
    name = "netease"

    def __init__(self, rate_limit_seconds: int | None = None):
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 1.0

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
        """Call NetEase POST /api/hr163/position/queryPage."""
        body = {
            "currentPage": 1,
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
            return []
        except Exception as e:
            logger.error(f"[NetEase] API error for '{keyword}': {e}")
            return []

        code = obj.get("code")
        data = obj.get("data", {})
        items = data.get("list", [])
        total = data.get("total", 0)

        if code != 200:
            logger.warning(f"[NetEase] API code={code} for '{keyword}'")
            return []

        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(self._api_item_to_job(item))
            except Exception as e:
                logger.debug(f"[NetEase] Skip item: {e}")
                continue

        logger.info(f"[NetEase] '{keyword}': {len(jobs)} jobs (total={total})")
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

        unique_id = hashlib.md5((f"netease{item_id}").encode()).hexdigest()[:16]  # nosec B324

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
        return job

    def normalize(self, raw: dict) -> Job:
        return Job(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            company=raw.get("company", ""),
            location=raw.get("location", ""),
            salary_min=raw.get("salary_min"),
            salary_max=raw.get("salary_max"),
            description=raw.get("description", ""),
            platforms=[self.name],
            urls={self.name: raw.get("url", "")},
        )
