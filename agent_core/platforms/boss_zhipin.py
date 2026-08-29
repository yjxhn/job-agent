"""Boss直聘 platform adapter using Playwright."""

import asyncio
import hashlib
import json
import logging
import re
import time
import urllib.request
from pathlib import Path

from agent_core.platforms.base import PlatformAdapter, parse_salary_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zhipin.com"

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
    """True if Boss session cookies (wt2 + __zp_stoken__) are present and valid.

    `expires` is a unix timestamp in seconds; <= 0 means a session cookie
    (no explicit expiry) — considered valid (the API will tell us if it's dead).
    """
    now = time.time()
    found = {}
    for c in cookies:
        if c.get("name") in ("wt2", "__zp_stoken__"):
            exp = c.get("expires", -1)
            found[c["name"]] = exp <= 0 or exp > now
    return all(found.get(k, False) for k in ("wt2", "__zp_stoken__"))


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

    def __init__(self, rate_limit_seconds: int | None = None, max_pages: int | None = None):
        self._detail_fetch_count = 0
        self._rate_limit_seconds: float = (
            rate_limit_seconds if rate_limit_seconds is not None else 1.5
        )
        self.max_pages = max_pages if max_pages and max_pages > 0 else 1
        self._ANTI_BOT_BACKOFF_SECONDS = 120  # code 37 = cookie flagged, moderate wait

    async def search(
        self,
        keywords,
        location,
        cookie_path=None,
        headless=False,
        rate_limit_seconds: int | None = None,
    ):
        """Search Boss直聘 via HTTP API (CDP detection blocks Playwright)."""
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds
        cookies = _load_cookies(cookie_path)
        if not cookies:
            logger.warning(f"[Boss] No cookie at {cookie_path}")
            _notify_cookie_expired()
            return []
        if not _session_cookie_valid(cookies):
            _notify_cookie_expired()
            return []
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        city_code = CITY_CODES.get(location, "100010000")

        jobs = []
        kw_list = keywords[:2]
        for idx, keyword in enumerate(kw_list):
            jobs.extend(
                await self._search_keyword_api(
                    keyword,
                    city_code,
                    cookie_str,
                    max_pages=self.max_pages,
                    rate_limit_seconds=self._rate_limit_seconds,
                )
            )
            # Only wait between requests — never after the final request.
            if idx < len(kw_list) - 1:
                await asyncio.sleep(self._rate_limit_seconds)
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
            # Wait before the NEXT page only; the final page has no tail sleep.
            if page < max_pages and job_list:
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
        """Fetch full JD for a Boss job.

        Strategy (in order of preference):
        1. HTML page fetch with cookies (fast, works for most pages)
           → falls through to Playwright if result is < 100 chars
        2. Playwright standalone browser (renders JS, cookie injection)
        3. Playwright persistent profile (requires manual login)
        4. wapi/card.json API fallback (rarely works due to anti-bot)

        Args:
            job: Job object with lid and security_id
            cookie_path: Path to Boss cookie JSON file

        Returns:
            Full JD text (truncated to 5000 chars) or "" on error
        """
        # Resolve real detail URL: prefer urls dict, fall back to lid
        detail_url = ""
        urls = getattr(job, "urls", {}) or {}
        if isinstance(urls, dict):
            detail_url = urls.get("boss_zhipin", "") or urls.get(self.name, "")
        if not detail_url:
            detail_url = getattr(job, "lid", "") or ""
        security_id = getattr(job, "security_id", "") or ""

        if not detail_url.startswith("http"):
            # Last resort: lid might be a search reference ID, not a URL
            lid = getattr(job, "lid", "") or ""
            if lid.startswith("http"):
                detail_url = lid

        cookies = _load_cookies(cookie_path)
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies) if cookies else ""

        _JD_MARKERS = ("岗位职责", "任职要求", "职位描述", "工作内容", "工作职责")

        # Method 1: HTML page fetch with cookies (fast path)
        if detail_url.startswith("http") and cookie_str:
            jd = await self._fetch_jd_from_html(detail_url, cookie_str)
            if jd:
                logger.info(f"[Boss] HTML fetch: {len(jd)} chars from {detail_url[:60]}")
                if any(kw in jd for kw in _JD_MARKERS):
                    return jd
                # HTML returned something but no real JD content —
                # page is likely JS-rendered, try Playwright
                logger.debug("[Boss] HTML result has no JD markers, trying Playwright")

        # Method 2: Playwright standalone browser (copes with JS rendering)
        if detail_url.startswith("http") and cookie_path:
            try:
                from agent_core.platforms.playwright_jd import fetch_jd_playwright

                jd = await fetch_jd_playwright(
                    url=detail_url,
                    platform="boss_zhipin",
                    cookie_path=cookie_path,
                    headless=False,
                )
                if jd and any(kw in jd for kw in _JD_MARKERS):
                    logger.info(f"[Boss] Playwright fetch: {len(jd)} chars")
                    return jd
            except RuntimeError as e:
                logger.warning(f"[Boss] Playwright unavailable ({e})")
            except Exception as e:
                logger.warning(f"[Boss] Playwright fetch failed: {e}")

        # Method 3: Playwright persistent profile (requires manual login)
        if detail_url.startswith("http"):
            try:
                from agent_core.platforms.boss_browser import fetch_jd as _boss_fetch_jd

                jd = await _boss_fetch_jd(detail_url, headless=False)
                if jd:
                    return jd
                logger.warning(f"[Boss] persistent-browser JD empty for {detail_url}")
            except RuntimeError as e:
                logger.warning(f"[Boss] persistent browser unavailable ({e})")
            except Exception as e:
                logger.warning(f"[Boss] persistent browser fetch failed for {detail_url}: {e}")

        # Method 4: wapi job-card endpoint (legacy, rarely works)
        if security_id and cookie_str:
            lid = getattr(job, "lid", "") or ""
            jd = await self._fetch_jd_detail(security_id, lid, cookie_str)
            if jd:
                return jd
        return ""

    async def _fetch_jd_from_html(self, url: str, cookie_str: str) -> str:
        """Fetch JD from job detail HTML page using cookies.

        This method directly requests the HTML page (not the JSON API) and
        extracts the job description from the rendered HTML. Works reliably
        as of 2026-07-09 (tested and confirmed working with valid cookies).
        """
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://www.zhipin.com/",
                "Cookie": cookie_str,
            },
        )

        def _fetch():
            with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                return r.read().decode("utf-8", "replace")

        try:
            html = await asyncio.to_thread(_fetch)

            # Check if we got the actual job page (not security challenge)
            if "passport/zp/security" in html:
                logger.warning("[Boss] HTML fetch redirected to security page")
                return ""

            if len(html) < 5000:
                logger.warning(f"[Boss] HTML too short ({len(html)} bytes), likely error page")
                return ""

            # Extract JD from job-sec div (main job description container)
            # Pattern matches: <div class="job-sec">...</div>
            jd_match = re.search(
                r'<div[^>]*class="[^"]*job-sec[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL
            )

            if jd_match:
                # Remove HTML tags and clean up whitespace
                jd_html = jd_match.group(1)
                jd_text = re.sub(r"<[^>]+>", " ", jd_html)
                jd_text = " ".join(jd_text.split())
                jd_text = jd_text.strip()

                if len(jd_text) > 10:
                    return jd_text[:5000]

            # Fallback: try to find JD-related sections in body text
            if any(kw in html for kw in ("岗位职责", "任职要求", "职位描述")):
                # Extract text around job-related keywords
                body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
                if body_match:
                    body_text = re.sub(r"<[^>]+>", " ", body_match.group(1))
                    body_text = " ".join(body_text.split())

                    # Try to slice from "岗位职责" or "任职要求"
                    for marker in ["岗位职责", "职位描述", "任职要求"]:
                        idx = body_text.find(marker)
                        if idx >= 0:
                            snippet = body_text[idx : idx + 3000]
                            return snippet.strip()[:5000]

            logger.warning("[Boss] Could not extract JD from HTML")
            return ""

        except Exception as e:
            logger.warning(f"[Boss] HTML fetch error: {e}")
            return ""

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
        job.education = j.get("jobDegree", "") or ""
        return job


async def boss_login(cookie_path="data/cookies/boss_zhipin.json", timeout_s=180):
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
    print("  4. 运行: job-agent import-cookies <export.json> boss_zhipin")
    return False


def _parse_salary(text):
    """Parse Boss salary strings via the shared cross-platform parser."""
    return parse_salary_text(text)
