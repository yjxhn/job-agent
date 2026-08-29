"""猎聘 platform adapter using direct HTTP API (no Playwright)."""

import asyncio
import hashlib
import json
import logging
import re
import secrets
import uuid
from pathlib import Path

from agent_core.platforms.base import PlatformAdapter, parse_salary_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.liepin.com"
SEARCH_API = "https://api-c.liepin.com/api/com.liepin.searchfront4c.pc-search-job"

# 猎聘 city codes (default empty string for nationwide; extend as needed)
CITY_CODES = {"全国": ""}  # TODO: add real city codes when tested


def _load_cookies(cookie_path):
    """Load cookies from a Playwright-format JSON file. Returns [] if missing/invalid."""
    if not cookie_path or not Path(cookie_path).exists():
        return []
    try:
        with open(cookie_path, encoding="utf-8") as f:
            cookies = json.load(f)
        if isinstance(cookies, list):
            logger.info(f"[猎聘] Loaded {len(cookies)} cookies from {cookie_path}")
            return cookies
    except Exception as e:
        logger.warning(f"[猎聘] Failed to load cookies from {cookie_path}: {e}")
    return []


def _session_cookie_valid(cookies):
    """True if 猎聘 session cookie (lt_auth) is present and not expired.

    `expires` is a unix timestamp in seconds; <= 0 means a session cookie
    (no explicit expiry) — considered valid (the API will tell us if it's dead).
    """
    import time

    now = time.time()
    for c in cookies:
        if c.get("name") == "lt_auth":
            exp = c.get("expires", -1)
            return exp <= 0 or exp > now
    return False  # no lt_auth at all


def _notify_cookie_expired(platform="猎聘"):
    """Fire a toast + log when the cookie is missing/expired/rejected."""
    logger.warning("[猎聘] Cookie expired or rejected — re-login required")
    try:
        from agent_core.notify.windows_toast import notify_cookie_expired

        notify_cookie_expired(platform)
    except Exception as e:
        logger.debug(f"Cookie-expired notify skipped: {e}")


class LiepinAdapter(PlatformAdapter):
    name = "liepin"

    def __init__(self, rate_limit_seconds: int | None = None, max_pages: int | None = None):
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 2.0
        self.max_pages = max_pages if max_pages and max_pages > 0 else 1

    async def search(
        self,
        keywords,
        location,
        cookie_path=None,
        headless=False,
        rate_limit_seconds: int | None = None,
    ):
        """Search 猎聘 via direct HTTP API.

        Uses the same JSON API the web frontend uses, authenticated with
        the saved cookie. `headless` is ignored (no browser).
        """
        # Use provided rate_limit_seconds or fall back to instance default
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds
        cookies = _load_cookies(cookie_path)
        if not cookies:
            logger.warning(
                f"[猎聘] No cookie at {cookie_path}; "
                f"run `job-agent login --platform liepin` or scripts/import_cookies.py first"
            )
            _notify_cookie_expired()
            return []
        if not _session_cookie_valid(cookies):
            _notify_cookie_expired()
            return []

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        city_code = CITY_CODES.get(location, "")  # default empty string = nationwide

        jobs = []
        kw_list = keywords[:2]
        for idx, keyword in enumerate(kw_list):
            jobs.extend(
                await self._search_keyword_api(keyword, city_code, cookie_str, rate_limit_seconds)
            )
            if idx < len(kw_list) - 1:
                await asyncio.sleep(self._rate_limit_seconds)
        logger.info(f"[猎聘] {len(jobs)} jobs total for keywords {keywords[:2]}")
        return jobs

    async def _search_keyword_api(self, keyword, city_code, cookie_str, rate_limit_seconds=None):
        """Call 猎聘 joblist JSON API for one keyword, paging per search_max_pages."""
        import urllib.error
        import urllib.request

        jobs = []
        for current_page in range(self.max_pages):
            # Build request body
            body_data = {
                "data": {
                    "mainSearchPcConditionForm": {
                        "city": city_code,
                        "dq": city_code,
                        "currentPage": current_page,
                        "pageSize": 40,
                        "key": keyword,
                        "suggestTag": "",
                        "workYearCode": "0",
                        "compId": "",
                        "compName": "",
                        "compTag": "",
                        "industry": "",
                        "salaryCode": "",
                        "jobKind": "",
                        "compScale": "",
                        "compKind": "",
                        "compStage": "",
                        "eduLevel": "",
                        "otherCity": "",
                        "salaryLow": "",
                        "salaryHigh": "",
                        "hrActiveTimeCode": "",
                    },
                    "passThroughForm": {
                        "sfrom": "search_job_pc",
                        "ckId": secrets.token_hex(16),
                        "scene": "input",
                        "skId": secrets.token_hex(16),
                        "fkId": secrets.token_hex(16),
                    },
                }
            }
            body = json.dumps(body_data, ensure_ascii=False).encode("utf-8")

            # Extract XSRF-TOKEN from cookie string
            xsrf_token = ""  # nosec B105 -- empty string init, not a password
            for pair in cookie_str.split(";"):
                pair = pair.strip()
                if pair.startswith("XSRF-TOKEN="):
                    xsrf_token = pair.split("=", 1)[1]
                    break

            req = urllib.request.Request(
                SEARCH_API,
                data=body,
                method="POST",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Origin": BASE_URL,
                    "Referer": f"{BASE_URL}/",
                    "X-Client-Type": "web",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-XSRF-TOKEN": xsrf_token,
                    "X-Fscp-Version": "1.1",
                    "X-Fscp-Std-Info": json.dumps({"client_id": "40108"}),
                    "X-Fscp-Trace-Id": str(uuid.uuid4()),
                    "Cookie": cookie_str,
                },
            )

            def _fetch():
                with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                    return r.read()

            try:
                raw = await asyncio.to_thread(_fetch)
                obj = json.loads(raw.decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                logger.error(f"[猎聘] API HTTP {e.code} for '{keyword}': {e.reason}")
                _notify_cookie_expired()
                return jobs
            except Exception as e:
                logger.error(f"[猎聘] API error for '{keyword}': {e}")
                _notify_cookie_expired()
                return jobs

            if obj.get("flag") != 1:
                code = obj.get("flag")
                msg = obj.get("msg", "")
                logger.warning(f"[猎聘] API flag={code} msg={msg} for '{keyword}'")
                _notify_cookie_expired()
                return jobs

            job_list = obj.get("data", {}).get("data", {}).get("jobCardList", [])
            if not job_list:
                logger.info(f"[猎聘] No jobs found for '{keyword}' (page {current_page + 1})")
                break

            for card in job_list:
                try:
                    jobs.append(self._api_item_to_job(card))
                except Exception as e:
                    logger.debug(f"[猎聘] Skip card: {e}")
                    continue

            logger.info(f"[猎聘] '{keyword}' page {current_page + 1}: {len(job_list)} jobs")
            # Wait before the NEXT page only.
            if current_page < self.max_pages - 1:
                await asyncio.sleep(rate_limit_seconds or self._rate_limit_seconds)

        return jobs

    def _api_item_to_job(self, card):
        """Map one 猎聘 API job item to a Job."""
        comp = card.get("comp", {})
        job = card.get("job", {})
        recruiter = card.get("recruiter", {})

        title = job.get("title", "")
        company = comp.get("compName", "")
        location = job.get("dq", "")
        sal_min, sal_max = _parse_salary(job.get("salary", ""))
        url = job.get("link", "")
        job_id = job.get("jobId", "")

        desc_parts = []
        if job.get("requireWorkYears"):
            desc_parts.append(f"经验: {job['requireWorkYears']}")
        if job.get("requireEduLevel"):
            desc_parts.append(f"学历: {job['requireEduLevel']}")
        if job.get("labels"):
            desc_parts.append("标签: " + "/".join(job["labels"]))
        if comp.get("compIndustry"):
            desc_parts.append(f"行业: {comp['compIndustry']}")
        if comp.get("compScale"):
            desc_parts.append(f"规模: {comp['compScale']}")
        if comp.get("compStage"):
            desc_parts.append(f"阶段: {comp['compStage']}")
        if recruiter.get("recruiterName"):
            desc_parts.append(f"HR: {recruiter['recruiterName']}")
        if recruiter.get("recruiterTitle"):
            desc_parts.append(f"HR职位: {recruiter['recruiterTitle']}")

        description = "\n".join(desc_parts)

        unique_id = hashlib.md5(  # nosec B324 -- job ID, not security
            (job_id or f"{company}{title}").encode()
        ).hexdigest()[:16]

        j = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": company,
                "location": location,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "description": description,
                "url": url,
            }
        )
        # Store jobId as security_id for on-demand JD fetching (Liepin uses jobId)
        j.security_id = job_id
        j.lid = url  # Use URL as lid for reference
        j.education = job.get("requireEduLevel", "") or ""
        return j

    async def fetch_full_jd(self, job, cookie_path) -> str:
        """Fetch full JD for a Liepin job.

        Uses Playwright to render the detail page (handles /a/ path pages
        that are JS-rendered and unreadable via static HTTP). Falls back to
        the legacy urllib+regex path only if Playwright is unavailable.

        Args:
            job: Job object with lid field containing the job URL
            cookie_path: Path to Liepin cookie JSON file

        Returns:
            Full JD text (truncated to 5000 chars) or empty string on error
        """
        if not job.lid or not job.lid.startswith("http"):
            logger.debug(f"[猎聘] Invalid or missing job URL for job {job.id}")
            return ""

        # Preferred path: Playwright render (handles /a/ and /job/ pages alike)
        try:
            from agent_core.platforms.playwright_jd import fetch_jd_playwright

            jd = await fetch_jd_playwright(
                url=job.lid,
                platform="liepin",
                cookie_path=cookie_path,
                headless=False,
            )
            if jd:
                return jd
            logger.warning(f"[猎聘] Playwright returned empty JD for {job.lid}")
            return ""
        except RuntimeError as e:
            # playwright not installed — fall through to legacy urllib path
            logger.warning(f"[猎聘] Playwright unavailable ({e}); falling back to urllib")
        except Exception as e:
            logger.warning(f"[猎聘] Playwright fetch failed for {job.lid}: {e}")
            return ""

        # Legacy fallback: static HTTP + regex (only works on /job/ pages)
        cookies = _load_cookies(cookie_path)
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        import urllib.request

        req = urllib.request.Request(
            job.lid,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cookie": cookie_str,
            },
        )

        def _fetch():
            with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                return r.read()

        try:
            raw = await asyncio.to_thread(_fetch)
            html = raw.decode("utf-8", "replace")
            for keyword in ["岗位职责", "任职要求", "职位描述", "岗位要求"]:
                pattern = rf"{keyword}[：:：]([^<]+)(?:<|$)"
                match = re.search(pattern, html)
                if match:
                    return match.group(1).strip()[:5000]
            for marker in ["job-detail-content", "job-description", "content-text"]:
                start = html.find(f"<{marker}")
                if start > 0:
                    end = html.find(f"</{marker}>", start)
                    if end > start:
                        content = html[start:end]
                        text = re.sub(r"<[^>]+>", "", content)
                        text = " ".join(text.split())
                        if len(text) > 100:
                            return text[:5000]
            logger.warning(f"[猎聘] Could not extract JD from {job.lid}")
            return ""
        except Exception as e:
            logger.warning(f"[猎聘] Failed to fetch JD from {job.lid}: {e}")
            return ""


async def liepin_login(cookie_path="data/cookies/liepin.json", timeout_s=180):
    """猎聘 auto-login via Playwright is unreliable. This function guides
    the user through the manual cookie-export flow instead. Always returns
    False (no automated cookie was obtained).
    """
    export_path = Path(cookie_path).parent / "liepin_export.json"
    print("\n[猎聘] 自动登录不可行（Playwright 容易被检测）。")
    print("请按手动流程获取 cookie：")
    print("  1. 在日常 Chrome 登录 https://www.liepin.com")
    print("  2. 用 Cookie-Editor 扩展导出 liepin.com 的全部 cookie 为 JSON（含 lt_auth）")
    print(f"  3. 保存为 {export_path}")
    print("  4. 运行: job-agent import-cookies <export.json> liepin --domain liepin.com")
    return False


def _parse_salary(text):
    """Parse Liepin salary strings via the shared cross-platform parser."""
    return parse_salary_text(text)
