"""BYD Careers adapter (job.byd.com) — public API, no login needed.

API discovery (2026-06-23):
  Endpoint: POST https://job.byd.com/portal/api/portal-api/position/queryList
  Body: {positionTypeArr, positionProvinceArr, positionCityArr,
    positionOrgArr, vagueCondition, searchType, zpType, pageNum, pageSize}
  zpType "00251" = social recruitment.
  Response: {code: 0, msg, data: {total, data: [{positionName, positionCode,
    city, province, fatherOrgAliasName, orgAliasName, peopleNumLimit,
    positionTypeId, createTime, divisionCode, detail}]}}
  No salary in list response.

Status: Live API confirmed 2026-06-23. No cookie/auth required.
"""

import asyncio
import hashlib
import json
import logging
import ssl
import urllib.error
import urllib.request

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

API_SEARCH = "https://job.byd.com/portal/api/portal-api/position/queryList"

_SSL_CONTEXT = ssl.create_default_context()


class BydAdapter(PlatformAdapter):
    name = "byd"

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
        """Search BYD Careers via public POST API. No cookie required."""
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        jobs: list[Job] = []
        for keyword in keywords[:3]:
            kw_jobs = await self._search_keyword_api(keyword, location)
            jobs.extend(kw_jobs)
            if len(keywords) > 1:
                await asyncio.sleep(self._rate_limit_seconds)

        logger.info(f"[BYD] {len(jobs)} jobs total for keywords {keywords[:3]}")
        return jobs

    async def _search_keyword_api(self, keyword: str, location: str) -> list[Job]:
        """Call BYD POST /portal/api/portal-api/position/queryList."""
        body = {
            "positionTypeArr": [],
            "positionProvinceArr": [],
            "positionCityArr": [],
            "positionOrgArr": [],
            "vagueCondition": keyword,
            "searchType": 1,
            "zpType": "00251",
            "pageNum": 0,
            "pageSize": 20,
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
                "Content-Type": "application/json",
                "lang": "zh_CN",
                "Referer": "https://job.byd.com/",
            },
            method="POST",
        )

        def _fetch() -> bytes:
            with urllib.request.urlopen(req, timeout=20, context=_SSL_CONTEXT) as r:  # nosec B310
                return r.read()

        try:
            raw = await asyncio.to_thread(_fetch)
            obj = json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            logger.error(f"[BYD] HTTP {e.code} for '{keyword}': {e.reason}")
            return []
        except Exception as e:
            logger.error(f"[BYD] API error for '{keyword}': {e}")
            return []

        code = obj.get("code")
        data = obj.get("data", {})
        items = data.get("data", [])
        total = data.get("total", 0)

        if code != 0:
            logger.warning(f"[BYD] API code={code} for '{keyword}'")
            return []

        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(self._api_item_to_job(item))
            except Exception as e:
                logger.debug(f"[BYD] Skip item: {e}")
                continue

        logger.info(f"[BYD] '{keyword}': {len(jobs)} jobs (total={total})")
        return jobs

    def _api_item_to_job(self, item: dict) -> Job:
        """Map one BYD position item to a Job.

        Keys: positionName, positionCode, city, province, fatherOrgAliasName,
        orgAliasName, peopleNumLimit, positionTypeId, createTime, divisionCode,
        detail.
        """
        position_code = str(item.get("positionCode", ""))
        title = item.get("positionName", "")

        province = item.get("province", "")
        city = item.get("city", "")
        if province and city and province != city:
            location = f"{province} {city}"
        elif city:
            location = city
        elif province:
            location = province
        else:
            location = ""

        father_org = item.get("fatherOrgAliasName", "")
        org = item.get("orgAliasName", "")

        # Build description
        desc_parts: list[str] = []
        if father_org:
            desc_parts.append(f"事业群: {father_org}")
        if org:
            desc_parts.append(f"部门: {org}")
        people = item.get("peopleNumLimit", 0)
        if people:
            desc_parts.append(f"招聘人数: {people}")
        detail = item.get("detail", "")
        if detail:
            desc_parts.append("")
            desc_parts.append(detail)

        description = "\n".join(desc_parts)

        # URL
        url = f"https://job.byd.com/portal/pc/#/social/socialPositionDetail?positionCode={position_code}"

        unique_id = hashlib.md5((f"byd{position_code}").encode()).hexdigest()[:16]  # nosec B324

        job = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": "比亚迪",
                "location": location,
                "salary_min": None,
                "salary_max": None,
                "description": description,
                "url": url,
            }
        )
        job.security_id = position_code
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
