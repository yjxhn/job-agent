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
DETAIL_URL = f"{BASE_URL}/tencentcareer/api/post/ByPostId"
JOB_URL_PREFIX = "http://careers.tencent.com/jobdesc.html?postId="

TENCENT_CATEGORY_ALIASES: dict[str, list[str]] = {
    "Tencent": [
        "腾讯",
        "Tencent",
        "深圳市腾讯计算机系统有限公司",
        "腾讯科技",
        "腾讯公司",
        "Tencent Holdings",
    ],
}


def _parse_salary_tencent(text: str) -> tuple[int | None, int | None]:
    """Parse Tencent salary strings. Tencent doesn't include salary in list API
    so this is for future detail-page parsing. Supports K/万/年薪 formats."""
    if not text:
        return None, None
    return _parse_salary(text)


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Parse '15K-25K' or '8千-1.2万' or '年薪30万' into (min, max) in yuan."""
    import re

    if not text:
        return None, None
    text = text.strip()

    # 年薪 format
    if "年薪" in text:
        m = re.findall(r"(\d+(?:\.\d+)?)", text)
        if m:
            amt = float(m[0]) * 10000
            return int(amt // 13), int(amt // 12)  # Monthly est

    # 万 format
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

    # K/k format
    if "K" in text or "k" in text:
        nums = re.findall(r"(\d+(?:\.\d+)?)", text)
        if len(nums) >= 2:
            return int(float(nums[0]) * 1000), int(float(nums[1]) * 1000)
        if len(nums) == 1:
            return int(float(nums[0]) * 1000), None
        return None, None

    # Pure number
    nums = re.findall(r"(\d+)", text)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        return int(nums[0]), None
    return None, None


class TencentAdapter(PlatformAdapter):
    name = "tencent"

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
        """Call Tencent GET /tencentcareer/api/post/Query."""
        ts = int(time.time() * 1000)
        params = {
            "timestamp": ts,
            "keyword": keyword,
            "pageIndex": 1,
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
            return []
        except Exception as e:
            logger.error(f"[Tencent] API error for '{keyword}': {e}")
            return []

        code = obj.get("Code")
        data = obj.get("Data", {})
        posts = data.get("Posts", [])
        total = data.get("Count", 0)

        if code != 200:
            logger.warning(f"[Tencent] API code={code} for '{keyword}'")
            return []

        jobs: list[Job] = []
        for post in posts:
            try:
                jobs.append(self._api_item_to_job(post))
            except Exception as e:
                logger.debug(f"[Tencent] Skip post: {e}")
                continue

        logger.info(f"[Tencent] '{keyword}': {len(jobs)} jobs (total={total})")
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
        location = f"{country} {city}".strip() if country else city
        if location == "中国":
            location = city

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
