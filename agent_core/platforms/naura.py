"""NAURA (北方华创) Careers adapter (career.naura.com) — session cookie needed.

API discovery (2026-06-23):
  Step 1: GET https://career.naura.com/campus to obtain session cookie.
  Step 2: POST https://career.naura.com/api/JobAd/GetJobAdPageList
  Body: {Category, PageIndex, PageSize, KeyWords, SpecialType, PortalId,
    DisplayFields}
  Category ["1"] = social recruitment, ["2"] = campus recruitment.
  PortalId extracted from page HTML: 16b1029a-bde1-4b4b-b2d1-f4fc052b5202

  Response: {Code: 200, Message, Count, Data: [{Id, JobAdId, JobAdName,
    Category, LocNames, Duty, Require, ChangeDate, Salary, Degree,
    YearsOfWorking}]}
  Note: LocNames and Salary are often empty/null in the list API for
  social recruitment positions.

Status: Live API confirmed 2026-06-23. Session cookie from /campus required.
"""

import asyncio
import hashlib
import json
import logging
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://career.naura.com"
SESSION_URL = f"{BASE_URL}/campus"
API_SEARCH = f"{BASE_URL}/api/JobAd/GetJobAdPageList"

# PortalId from page HTML (verified 2026-06-23)
PORTAL_ID = "16b1029a-bde1-4b4b-b2d1-f4fc052b5202"


class NauraAdapter(PlatformAdapter):
    name = "naura"

    def __init__(self, rate_limit_seconds: int | None = None):
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 1.0
        self._cj: CookieJar | None = None
        self._opener: urllib.request.OpenerDirector | None = None
        self._session_ready = False

    def _ensure_session(self) -> urllib.request.OpenerDirector:
        """Get or create an opener with a valid session cookie."""
        if self._session_ready and self._opener is not None:
            return self._opener

        self._cj = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cj))

        def _init_session() -> None:
            req = urllib.request.Request(
                SESSION_URL,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                method="GET",
            )
            with self._opener.open(req, timeout=20) as r:  # type: ignore[union-attr]  # nosec B310
                r.read()

        loop = asyncio.get_event_loop()
        init_future = loop.run_in_executor(None, _init_session)

        def _on_done(fut):
            try:
                fut.result()
                self._session_ready = True
            except Exception as e:
                logger.error(f"[NAURA] Session init failed: {e}")
                self._session_ready = False

        # Block until session is ready (adapter search is async anyway)
        try:
            init_future.result(timeout=15)  # type: ignore[call-arg]
            self._session_ready = True
        except Exception as e:
            logger.error(f"[NAURA] Session init failed: {e}")
            self._session_ready = False

        return self._opener  # type: ignore[return-value]

    async def search(
        self,
        keywords: list[str],
        location: str,
        cookie_path: str | None = None,
        headless: bool = False,
        rate_limit_seconds: int | None = None,
    ) -> list[Job]:
        """Search NAURA Careers via POST API with session cookie."""
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        # Ensure we have a session cookie before making API calls
        self._ensure_session()

        jobs: list[Job] = []
        for keyword in keywords[:3]:
            kw_jobs = await self._search_keyword_api(keyword, location)
            jobs.extend(kw_jobs)
            if len(keywords) > 1:
                await asyncio.sleep(self._rate_limit_seconds)

        logger.info(f"[NAURA] {len(jobs)} jobs total for keywords {keywords[:3]}")
        return jobs

    async def _search_keyword_api(self, keyword: str, location: str) -> list[Job]:
        """Call NAURA POST /api/JobAd/GetJobAdPageList."""
        if self._opener is None:
            logger.error("[NAURA] No session opener available")
            return []

        body = {
            "Category": ["1"],
            "PageIndex": 0,
            "PageSize": 20,
            "KeyWords": keyword,
            "SpecialType": 0,
            "PortalId": PORTAL_ID,
            "DisplayFields": ["Category"],
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
                "Referer": f"{BASE_URL}/campus",
                "Origin": BASE_URL,
            },
            method="POST",
        )

        def _fetch() -> bytes:
            with self._opener.open(req, timeout=20) as r:  # type: ignore[union-attr]  # nosec B310
                return r.read()

        try:
            raw = await asyncio.to_thread(_fetch)
            obj = json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            logger.error(f"[NAURA] HTTP {e.code} for '{keyword}': {e.reason}")
            return []
        except Exception as e:
            logger.error(f"[NAURA] API error for '{keyword}': {e}")
            return []

        code = obj.get("Code")
        items = obj.get("Data", [])
        total = obj.get("Count", 0)

        if code != 200:
            logger.warning(f"[NAURA] API Code={code} for '{keyword}'")
            return []

        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(self._api_item_to_job(item))
            except Exception as e:
                logger.debug(f"[NAURA] Skip item: {e}")
                continue

        logger.info(f"[NAURA] '{keyword}': {len(jobs)} jobs (total={total})")
        return jobs

    def _api_item_to_job(self, item: dict) -> Job:
        """Map one NAURA JobAd item to a Job.

        Keys: Id, JobAdId, JobAdName, Category, LocNames, Duty, Require,
        ChangeDate, Salary, Degree, YearsOfWorking.
        """
        job_ad_id = str(item.get("JobAdId", ""))
        title = item.get("JobAdName", "")

        # LocNames is often empty for social recruitment positions
        loc_names = item.get("LocNames", [])
        if isinstance(loc_names, list) and loc_names:
            location = " ".join(loc_names)
        elif isinstance(loc_names, str) and loc_names:
            location = loc_names
        else:
            location = ""

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

        description = "\n".join(desc_parts)

        change_date = item.get("ChangeDate", "")
        if change_date:
            desc_parts.append(f"\n更新: {change_date}")

        description = "\n".join(desc_parts)

        # NAURA list API Salary is often None; handle gracefully
        # No salary parsing needed since it's usually null

        # URL
        item_id = item.get("Id", "")
        url = f"{BASE_URL}/campus/position/{item_id}" if item_id else ""

        unique_id = hashlib.md5((f"naura{job_ad_id}").encode()).hexdigest()[:16]  # nosec B324

        job = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": "北方华创",
                "location": location,
                "salary_min": None,
                "salary_max": None,
                "description": description,
                "url": url,
            }
        )
        job.security_id = job_ad_id
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
