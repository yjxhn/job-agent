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

Known issues (2026-06-28):
  - vagueCondition rejects Chinese characters with HTTP 400.
  - API pagination is broken (pages overlap 80-95% regardless of pageSize).
  - English keywords (e.g. "Python") return 0 results because BYD genuinely
    has few software positions.
  Workaround: discover positionTypeIds from one no-filter call, then fetch
  one page per type (pageSize=100) to cover ~666 unique jobs (~28% of total).

Status: Live API confirmed 2026-06-28. No cookie/auth required.
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
_PAGE_SIZE = 100  # max per request; BYD pagination is broken (pages 80-95% overlap)

_SSL_CONTEXT = ssl.create_default_context()


class BydAdapter(PlatformAdapter):
    name = "byd"

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

    def _build_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "lang": "zh_CN",
            "Referer": "https://job.byd.com/",
        }

    def _build_body(self, keyword: str, page_num: int = 0, page_size: int | None = None) -> bytes:
        body = {
            "positionTypeArr": [],
            "positionProvinceArr": [],
            "positionCityArr": [],
            "positionOrgArr": [],
            "vagueCondition": keyword,
            "searchType": 1,
            "zpType": "00251",
            "pageNum": page_num,
            "pageSize": page_size if page_size is not None else _PAGE_SIZE,
        }
        return json.dumps(body).encode("utf-8")

    async def _search_keyword_api(self, keyword: str, location: str) -> list[Job]:
        """Call BYD POST API with keyword, paging per search_max_pages.

        BYD pagination is known to overlap heavily (80-95%), so duplicate job
        IDs are expected and handled by the cross-platform dedup layer.
        """
        if not keyword:
            return []

        jobs: list[Job] = []
        for page_num in range(self.max_pages):
            try:
                req = urllib.request.Request(
                    API_SEARCH,
                    data=self._build_body(keyword, page_num=page_num),
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
                code = obj.get("code")

                if code == 0:
                    data = obj.get("data", {})
                    items = data.get("data", [])
                    total = data.get("total", 0)
                    if items:
                        jobs.extend(self._parse_items(items))
                        logger.info(
                            "[BYD] keyword '%s' page %d: %d jobs (API total=%d)",
                            keyword,
                            page_num + 1,
                            len(items),
                            total,
                        )
                        if page_num < self.max_pages - 1:
                            await asyncio.sleep(self._rate_limit_seconds)
                        continue
                logger.info(
                    "[BYD] Keyword '%s' page %d yielded 0 API results, returning empty "
                    "(fallback removed)",
                    keyword,
                    page_num + 1,
                )
                break
            except urllib.error.HTTPError as e:
                # 2026-08-11 用户决策：不再 fallback 全量客户端过滤。
                logger.info(
                    "[BYD] Keyword API rejected '%s' (HTTP %d), returning empty (fallback removed)",
                    keyword,
                    e.code,
                )
                break
            except Exception as e:
                logger.error("[BYD] API error for '%s': %s", keyword, e)
                break

        return jobs

    def _parse_items(self, items: list[dict]) -> list[Job]:
        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(self._api_item_to_job(item))
            except Exception as e:
                logger.debug("[BYD] Skip item: %s", e)
                continue
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

        fallback = f"{title}|{location}" if title else position_code
        unique_id = hashlib.md5(  # nosec B324 -- job ID, not security
            (f"byd{position_code or fallback}").encode()
        ).hexdigest()[:16]

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
        job.lid = url  # detail URL so fetch_full_jd can actually run
        job.published_at = item.get("createTime", "") or ""
        return job
