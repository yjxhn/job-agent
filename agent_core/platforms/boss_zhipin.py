"""Boss直聘 platform adapter using Playwright."""

import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zhipin.com"
SEARCH_URL = f"{BASE_URL}/web/geek/job"
LOGIN_URL = f"{BASE_URL}/web/user/?ka=header-login"

# Whether to fetch full JD details (default False to avoid anti-bot risk)
FETCH_FULL_JD = False

# Boss直聘 city codes (partial — extend as needed)
CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "苏州": "101190400",
    "宁德": "101230300",
    "常州": "101190500",
}


def _load_cookies(cookie_path):
    """Load cookies from a Playwright-format JSON file. Returns [] if missing/invalid."""
    if not cookie_path or not Path(cookie_path).exists():
        return []
    try:
        with open(cookie_path, encoding="utf-8") as f:
            cookies = json.load(f)
        if isinstance(cookies, list):
            logger.info(f"[Boss] Loaded {len(cookies)} cookies from {cookie_path}")
            return cookies
    except Exception as e:
        logger.warning(f"[Boss] Failed to load cookies from {cookie_path}: {e}")
    return []


def _session_cookie_valid(cookies):
    """True if the Boss session cookie (wt2) is present and not expired.

    `expires` is a unix timestamp in seconds; <= 0 means a session cookie
    (no explicit expiry) — considered valid (the API will tell us if it's dead).
    """
    now = time.time()
    for c in cookies:
        if c.get("name") == "wt2":
            exp = c.get("expires", -1)
            return exp <= 0 or exp > now
    return False  # no wt2 at all


def _notify_anti_bot(platform="Boss直聘"):
    """Fire a toast + log when anti-bot challenge (code 37) is triggered."""
    logger.warning(
        f"[Boss] Anti-bot challenge triggered ({platform}) — retry later or re-export cookie"
    )
    try:
        from agent_core.notify.windows_toast import notify_anti_bot

        notify_anti_bot(platform)
    except Exception as e:
        logger.debug(f"Anti-bot notify skipped: {e}")


def _notify_cookie_expired(platform="Boss直聘"):
    """Fire a toast + log when the cookie is missing/expired/rejected."""
    logger.warning("[Boss] Cookie expired or rejected — re-login required")
    try:
        from agent_core.notify.windows_toast import notify_cookie_expired

        notify_cookie_expired(platform)
    except Exception as e:
        logger.debug(f"Cookie-expired notify skipped: {e}")


class BossZhipinAdapter(PlatformAdapter):
    name = "boss_zhipin"

    def __init__(self, rate_limit_seconds: int | None = None):
        self._detail_fetch_count = 0
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 1.5
        self._ANTI_BOT_BACKOFF_SECONDS = rate_limit_seconds if rate_limit_seconds else 300

    async def search(
        self,
        keywords,
        location,
        cookie_path=None,
        headless=False,
        rate_limit_seconds: int | None = None,
    ):
        """Search Boss直聘 via direct HTTP API.

        Boss detects CDP-controlled browsers (Playwright) and serves a blank
        page, so we bypass the browser entirely and call the same JSON API the
        web frontend uses, authenticated with the saved cookie.
        `headless` is ignored (no browser).
        """
        # Use provided rate_limit_seconds or fall back to instance default
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds
        cookies = _load_cookies(cookie_path)
        if not cookies:
            logger.warning(
                f"[Boss] No cookie at {cookie_path}; "
                f"run `job-agent login --platform boss` or import_cookies.py first"
            )
            _notify_cookie_expired()
            return []
        if not _session_cookie_valid(cookies):
            _notify_cookie_expired()
            return []
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        city_code = CITY_CODES.get(location, "100010000")

        jobs = []
        for keyword in keywords[:2]:
            jobs.extend(
                await self._search_keyword_api(keyword, city_code, cookie_str, rate_limit_seconds)
            )
            await asyncio.sleep(2)  # inter-keyword rate limit
        logger.info(f"[Boss] {len(jobs)} jobs total for keywords {keywords[:2]}")
        return jobs

    async def _search_keyword_api(
        self,
        keyword,
        city_code,
        cookie_str,
        max_pages=1,
        rate_limit_seconds: float = 1.5,
    ):
        """Call Boss joblist JSON API for one keyword."""
        import urllib.error
        import urllib.parse
        import urllib.request

        jobs = []
        for page in range(1, max_pages + 1):
            params = urllib.parse.urlencode({"query": keyword, "city": city_code, "page": page})
            url = f"https://www.zhipin.com/wapi/zpgeek/search/joblist.json?{params}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Referer": (
                        f"https://www.zhipin.com/web/geek/job?"
                        f"query={urllib.parse.quote(keyword)}&city={city_code}"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
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
                logger.error(f"[Boss] API HTTP {e.code} for '{keyword}' p{page}: {e.reason}")
                break
            except Exception as e:
                logger.error(f"[Boss] API error for '{keyword}' p{page}: {e}")
                break

            if obj.get("code") != 0:
                code = obj.get("code")
                msg = obj.get("message")
                zpdata = obj.get("zpData", {})
                # Detect anti-bot challenge (code 37 or challenge markers in zpData)
                is_anti_bot = (
                    code == 37
                    or isinstance(zpdata, dict)
                    and any(key in zpdata for key in ("seed", "name", "ts"))
                )
                logger.warning(f"[Boss] API code={code} msg={msg} for '{keyword}'")
                if is_anti_bot:
                    logger.warning(
                        "[Boss] Anti-bot challenge (code 37), access flagged as abnormal"
                    )  # noqa: E501
                    logger.warning(
                        f"[Boss] Backing off for {self._ANTI_BOT_BACKOFF_SECONDS}s "
                        "to avoid repeated blocking"
                    )
                    _notify_anti_bot()
                    await asyncio.sleep(self._ANTI_BOT_BACKOFF_SECONDS)
                    break
                else:
                    # Other non-zero codes typically mean auth/cookie failure
                    _notify_cookie_expired()
                break
            job_list = obj.get("zpData", {}).get("jobList", [])
            if not job_list:
                break
            for j in job_list:
                jobs.append(await self._api_item_to_job(j, cookie_str))
            logger.info(f"[Boss] '{keyword}' page {page}: {len(job_list)} jobs")
            await asyncio.sleep(self._rate_limit_seconds)
        return jobs

    async def _fetch_jd_detail(self, security_id, lid, cookie_str) -> str:
        """Fetch full JD description from job card API.

        Returns the postDescription text (truncated to 5000 chars),
        or empty string on any error/missing field.
        """
        import urllib.parse
        import urllib.request

        url = f"https://www.zhipin.com/wapi/zpgeek/job/card.json?securityId={security_id}&lid={lid}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.zhipin.com/web/geek/job",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cookie": cookie_str,
            },
        )

        def _fetch():
            with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                return r.read()

        try:
            raw = await asyncio.to_thread(_fetch)
            obj = json.loads(raw.decode("utf-8", "replace"))
            # Try multiple possible paths (defensive, real field untested due to API blocking)
            zpdata = obj.get("zpData", {})
            if isinstance(zpdata, dict):
                for path in (
                    ("jobCard", "postDescription"),
                    ("postDescription",),
                    ("jobInfo", "postDescription"),
                ):
                    cur: object = zpdata
                    for key in path:
                        cur = cur.get(key) if isinstance(cur, dict) else None
                        if cur is None:
                            break
                    if cur:
                        return str(cur).strip()[:5000]
        except Exception:
            # Any error returns empty string
            pass
        return ""

    async def fetch_full_jd(self, job, cookie_path) -> str:
        """Convenience method to fetch full JD for a single job.

        Args:
            job: Job object with security_id and lid fields
            cookie_path: Path to Boss cookie JSON file

        Returns:
            Full JD text (truncated to 5000 chars) or empty string on error
        """
        if not job.security_id or not job.lid:
            logger.debug(f"[Boss] Missing security_id or lid for job {job.id}")
            return ""

        cookies = _load_cookies(cookie_path)
        if not cookies:
            logger.warning(f"[Boss] No cookie at {cookie_path}")
            return ""
        if not _session_cookie_valid(cookies):
            logger.warning(f"[Boss] Cookie expired or invalid at {cookie_path}")
            return ""

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        return await self._fetch_jd_detail(job.security_id, job.lid, cookie_str)

    async def _api_item_to_job(self, j, cookie_str=""):
        """Map one Boss API job item to a Job."""
        title = j.get("jobName", "")
        company = j.get("brandName", "")
        loc_parts = [j.get("cityName"), j.get("areaDistrict"), j.get("businessDistrict")]
        location = "-".join(p for p in loc_parts if p)
        sal_min, sal_max = _parse_salary(j.get("salaryDesc", ""))
        encrypt_id = j.get("encryptJobId", "")
        link = f"{BASE_URL}/job_detail/{encrypt_id}.html" if encrypt_id else ""

        desc_parts = []
        if j.get("jobExperience"):
            desc_parts.append(f"经验: {j['jobExperience']}")
        if j.get("jobDegree"):
            desc_parts.append(f"学历: {j['jobDegree']}")
        if j.get("skills"):
            desc_parts.append("技能: " + "/".join(j["skills"]))
        if j.get("jobLabels"):
            desc_parts.append("标签: " + "/".join(j["jobLabels"]))
        if j.get("welfareList"):
            desc_parts.append("福利: " + "/".join(j["welfareList"]))
        if j.get("brandIndustry"):
            desc_parts.append(f"行业: {j['brandIndustry']}")
        if j.get("brandScaleName"):
            desc_parts.append(f"规模: {j['brandScaleName']}")
        description = "\n".join(desc_parts)

        # Optional: fetch full JD detail if enabled (DEPRECATED - now use on-demand fetch_full_jd)
        # This code block removed to avoid code-37 anti-bot triggering during search

        job_id = hashlib.md5(  # nosec B324 -- job ID, not security
            (encrypt_id or f"{company}{title}").encode()
        ).hexdigest()[:16]
        job = self.normalize(
            {
                "id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "description": description,
                "url": link,
            }
        )
        # Store security_id and lid for on-demand JD fetching
        job.security_id = j.get("securityId", "")
        job.lid = j.get("lid", "")
        return job

    def normalize(self, raw):
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


async def boss_login(cookie_path="data/cookies/boss.json", timeout_s=180):
    """Boss直聘 detects the CDP protocol, so Playwright auto-login is impossible
    (the browser is redirected to a blank page). This function guides the user
    through the manual cookie-export flow instead. Always returns False
    (no automated cookie was obtained).
    """
    export_path = Path(cookie_path).parent / "boss_export.json"
    print("\n[Boss] 自动登录不可行（Boss 检测 CDP 协议，Playwright 会被重定向到空白页）。")
    print("请按手动流程获取 cookie：")
    print("  1. 在日常 Chrome 登录 https://www.zhipin.com")
    print("  2. 用 Cookie-Editor 扩展导出 zhipin.com 的全部 cookie 为 JSON（含 wt2）")
    print(f"  3. 保存为 {export_path}")
    print("  4. 运行: job-agent import-cookies <export.json> boss --domain zhipin.com")
    return False


def _parse_salary(text):
    """Parse '8-13K', '8K-12K', '15K' into (min, max) integers."""
    if not text or ("K" not in text and "k" not in text):
        return None, None
    nums = re.findall(r"(\d+(?:\.\d+)?)", text)
    if len(nums) >= 2:
        return int(float(nums[0]) * 1000), int(float(nums[1]) * 1000)
    if len(nums) == 1:
        return int(float(nums[0]) * 1000), None
    return None, None
