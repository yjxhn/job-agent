"""智联招聘 platform adapter with dual-mode search.

Primary (recommended): Playwright browser-based search.
  Launches real Chromium to let Akamai Bot Manager JS generate the
  dynamic URL token (MmEwMD, c1K5tw0w6_) and sensor data. Browser
  intercepts the fe-api XHR response and extracts job listings.
  Requires: pip install playwright && playwright install chromium.

Fallback: Direct HTTP API (POST fe-api.zhaopin.com/c/i/search/positions).
  Uses at/rt cookies only. May be soft-blocked by Akamai when URL
  tokens are required, resulting in count>0 but list empty.

API discovery (2026-06-21, endpoint corrected 2026-06-21):
  Primary endpoint: POST https://fe-api.zhaopin.com/c/i/search/positions
  JSON body: {S_SOU_FULL_INDEX, S_SOU_WORK_CITY, pageSize, pageIndex, ...}
  Response shape: {code, apiCode, data: {count, list: [{name, companyName,
    salary60, ...}]}}

Anti-bot note: The GET /c/i/sou endpoint is Akamai-protected (always
  returns count=0). The POST /c/i/search/positions works with valid
  cookies but may require Akamai URL tokens for consistent results.

Status: Browser mode verified 2026-06-24 (Phase 1 POC passed).
  POST endpoint confirmed working with valid cookies + x-zp-* headers,
  but susceptible to soft-blocks without Akamai tokens.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from agent_core.platforms.base import Job, PlatformAdapter, parse_salary_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zhaopin.com"
# Working POST endpoint (GET /c/i/sou returns count=0 due to Akamai)
API_SEARCH = "https://fe-api.zhaopin.com/c/i/search/positions"

# 智联 city codes (partial — extend as needed via cityId from API)
CITY_CODES: dict[str, str] = {
    "全国": "0",
    "北京": "489",
    "上海": "538",
    "广州": "763",
    "深圳": "765",
    "杭州": "653",
    "成都": "801",
    "武汉": "736",
    "南京": "635",
    "苏州": "639",
    "常州": "638",  # From user cookie LastCity_id
    "宁德": "854",
    "佛山": "531",
}


def _load_cookies(cookie_path: str | None) -> list[dict]:
    """Load cookies from a Playwright-format JSON file. Returns [] if missing/invalid."""
    if not cookie_path or not Path(cookie_path).exists():
        return []
    try:
        with open(cookie_path, encoding="utf-8") as f:
            cookies = json.load(f)
        if isinstance(cookies, list):
            logger.info(f"[智联] Loaded {len(cookies)} cookies from {cookie_path}")
            return cookies
    except Exception as e:
        logger.warning(f"[智联] Failed to load cookies from {cookie_path}: {e}")
    return []


class ZhilianAdapter(PlatformAdapter):
    name = "zhilian"

    def __init__(
        self,
        rate_limit_seconds: int | None = None,
        browser_profile_dir: str | None = None,
        max_pages: int | None = None,
    ):
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 2.0
        # Anti-bot backoff is independent of rate limiting: a short
        # rate_limit_seconds (e.g. 1-2s) must NOT shrink the anti-bot
        # cooldown, or a soft block would be "backed off" for only a
        # second. Fixed at 300s (matches the original design).
        self._ANTI_BOT_BACKOFF_SECONDS = 300
        self.max_pages = max_pages if max_pages and max_pages > 0 else 1
        self._browser_profile_dir = browser_profile_dir or "data/zhilian_browser_profile"

    async def search(
        self,
        keywords: list[str],
        location: str,
        cookie_path: str | None = None,
        headless: bool = False,
        rate_limit_seconds: int | None = None,
    ) -> list[Job]:
        """Search 智联招聘 via Playwright browser (primary) or HTTP API (fallback).

        Browser mode (default): Launches Chromium with persistent profile,
        navigates to sou.zhaopin.com, intercepts fe-api XHR responses.
        Akamai tokens (MmEwMD, c1K5tw0w6_) are generated automatically
        by the browser JS -- no manual token crafting needed.

        Fallback mode (when browser unavailable): Uses the existing HTTP
        POST to fe-api.zhaopin.com/c/i/search/positions with at/rt cookies.
        May be soft-blocked by Akamai (count>0, list empty).

        Args:
            keywords: Search keywords (max 2 used)
            location: City name (maps to city code)
            cookie_path: Cookie JSON path (for HTTP fallback mode)
            headless: Run browser headless (more detectable; default False)
            rate_limit_seconds: Override per-request rate limit
        """
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        city_code = CITY_CODES.get(location, "0")

        # Try browser mode first
        try:
            from agent_core.platforms.zhilian_browser import get_browser

            browser = await get_browser(profile_dir=self._browser_profile_dir, headless=headless)
            jobs: list[Job] = []
            for keyword in keywords[:2]:
                items = await browser.search(
                    keyword=keyword,
                    city_code=city_code,
                    headless=headless,
                )
                for item in items:
                    try:
                        jobs.append(self._api_item_to_job(item))
                    except Exception as e:
                        logger.debug(f"[智联] Skip item: {e}")
                        continue
                if len(keywords[:2]) > 1:
                    await asyncio.sleep(2)

            if jobs:
                logger.info(f"[智联] Browser mode: {len(jobs)} jobs for {keywords[:2]}")
                return jobs
            logger.warning("[智联] Browser returned 0 results (API fallback disabled)")
            return []
        except Exception as e:
            logger.error(f"[智联] Browser mode failed: {e}")
            return []

    def _api_item_to_job(self, item: dict) -> Job:
        """Map one 智联 API data.list item to a Job.

        Real field structure (from /c/i/search/positions API response):
          name, companyName, salary60, education, workingExp, workCity,
          cityDistrict, cityId, positionURL, number, companySize,
          industryName, workType, welfareLabel, publishTime,
          jobDetailData: {position: {base: {positionName, salary, ...},
          desc: {description, ...}, workLocation: {address, ...}}}
        """
        # Top-level flat fields (not nested dicts)
        title = item.get("name", "")
        company_name = item.get("companyName", "")
        if not company_name:
            # Fallback: try old nested format
            comp = item.get("company", {}) or {}
            company_name = comp.get("name", "") if isinstance(comp, dict) else ""

        salary = item.get("salary60", "")
        if not salary:
            jdd = item.get("jobDetailData", {}) or {}
            pos = jdd.get("position", {}) or {}
            base = pos.get("base", {}) or {}
            salary = base.get("salary", "")
        sal_min, sal_max = _parse_salary(salary)

        city_display = item.get("workCity", "")
        district = item.get("cityDistrict", "")
        if district and district != city_display:
            city_display = f"{city_display} {district}"

        url = item.get("positionURL", "")
        job_number = item.get("number", "")
        unique_id = hashlib.md5(  # nosec B324 -- job ID, not security
            (job_number or f"{company_name}{title}").encode()
        ).hexdigest()[:16]

        # Build description from flat fields + nested desc
        desc_parts: list[str] = []
        education = item.get("education", "")
        working_exp = item.get("workingExp", "")
        if education:
            desc_parts.append(f"学历: {education}")
        if working_exp:
            desc_parts.append(f"经验: {working_exp}")
        industry = item.get("industryName", "")
        if industry and industry not in desc_parts:
            desc_parts.append(f"行业: {industry}")
        company_size = item.get("companySize", "")
        if company_size:
            desc_parts.append(f"规模: {company_size}")
        work_type = item.get("workType", "")
        if work_type:
            desc_parts.append(f"类型: {work_type}")
        welfare = item.get("welfareLabel", [])
        if welfare:
            desc_parts.append("福利: " + "/".join(w for w in welfare if w))

        # Append full job description from nested data if available
        jdd = item.get("jobDetailData", {}) or {}
        pos = jdd.get("position", {}) or {}
        desc_obj = pos.get("desc", {}) or {}
        full_desc = desc_obj.get("description", "") if isinstance(desc_obj, dict) else ""
        if full_desc:
            desc_parts.append(full_desc)

        description = "\n".join(desc_parts)

        job = self.normalize(
            {
                "id": unique_id,
                "title": title,
                "company": company_name,
                "location": city_display,
                "salary_min": sal_min,
                "salary_max": sal_max,
                "description": description,
                "url": url,
            }
        )
        job.security_id = job_number
        job.lid = url
        job.published_at = item.get("publishTime", "") or ""
        job.education = item.get("education", "") or ""
        return job

    async def fetch_full_jd(self, job, cookie_path: str) -> str:
        """Fetch full JD for a Zhilian job.

        Strategy:
        1. Reuse the persistent zhilian browser (singleton) when available —
           its CDN cookies bypass Tencent Cloud EdgeOne which would otherwise
           block a standalone Playwright context with a CAPTCHA.
        2. Fall back to standalone playwright_jd browser.
        3. Last resort: static HTTP (rarely works, JS-rendered pages).

        Args:
            job: Job object with lid (detail URL) and security_id
            cookie_path: Path to Zhilian cookie JSON file

        Returns:
            Full JD text (truncated to 5000 chars) or "" on error
        """
        import re

        # Short-circuit: zhilian search API already includes full JD via
        # jobDetailData.position.desc.description.  If the description has
        # "岗位职责" or "任职要求" it's already complete — don't waste a
        # browser launch (and risk EdgeOne CAPTCHA) for nothing.
        desc = job.description or ""
        if any(kw in desc for kw in ("岗位职责", "任职要求", "工作职责", "岗位要求")):
            logger.info("[智联] JD already present from search API, skipping fetch")
            return ""

        lid = getattr(job, "lid", "") or ""
        if not lid.startswith("http"):
            return ""

        # Strategy 1: use persistent zhilian browser (bypasses CDN CAPTCHA)
        try:
            from agent_core.platforms.zhilian_browser import get_browser as _get_zl_browser

            zl_browser = await _get_zl_browser(
                profile_dir=self._browser_profile_dir, headless=False
            )
            page = await zl_browser._context.new_page()
            try:
                await page.goto(lid, wait_until="domcontentloaded", timeout=20000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                jd = ""
                for sel in (
                    ".describtion__detail-content",
                    ".job-description",
                    "[class*='description']",
                    "[class*='job-detail']",
                ):
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            text = (await el.inner_text()).strip()
                            if text and len(text) > 50:
                                jd = text
                                break
                    except Exception:
                        continue
                if not jd:
                    try:
                        body = (await page.inner_text("body")).strip()
                    except Exception:
                        body = ""
                    if body:
                        from agent_core.platforms.playwright_jd import _slice_jd_from_body

                        jd = _slice_jd_from_body(body, "zhilian")
                if jd and len(jd) > 50:
                    logger.info(f"[智联] Fetched JD via persistent browser: {len(jd)} chars")
                    return jd[:5000]
            finally:
                await page.close()
        except Exception as e:
            logger.debug(f"[智联] Persistent browser JD fetch: {e}")

        # Strategy 2: standalone playwright_jd browser
        try:
            from agent_core.platforms.playwright_jd import fetch_jd_playwright

            jd = await fetch_jd_playwright(
                url=lid,
                platform="zhilian",
                cookie_path=cookie_path,
                headless=False,
            )
            if jd and len(jd) > 50:
                logger.info(f"[智联] Fetched JD via playwright_jd: {len(jd)} chars")
                return jd[:5000]
        except Exception as e:
            logger.warning(f"[智联] Playwright JD fetch failed: {e}")

        # Fallback: Try HTTP fetch with cookies (rarely works due to JS rendering)
        cookies = _load_cookies(cookie_path)
        if not cookies:
            logger.debug("[智联] No cookies for HTTP JD fetch")
            return ""

        import urllib.request

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        req = urllib.request.Request(
            lid,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": BASE_URL,
                "Cookie": cookie_str,
            },
        )

        def _fetch():
            with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                return r.read().decode("utf-8", "replace")

        try:
            html = await asyncio.to_thread(_fetch)

            # Try to extract JD from HTML
            # Zhilian JD is usually in <div class="describtion__detail-content">
            jd_match = re.search(
                r'<div[^>]*class="[^"]*describtion[^"]*"[^>]*>(.*?)</div>',
                html,
                re.DOTALL | re.IGNORECASE,
            )
            if jd_match:
                jd_text = re.sub(r"<[^>]+>", " ", jd_match.group(1))
                jd_text = " ".join(jd_text.split())
                if len(jd_text) > 50:
                    return jd_text[:5000]

            # Fallback: look for 岗位职责 or 职位描述
            if "岗位职责" in html or "职位描述" in html:
                body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
                if body_match:
                    body_text = re.sub(r"<[^>]+>", " ", body_match.group(1))
                    body_text = " ".join(body_text.split())
                    for marker in ["岗位职责", "职位描述", "任职要求"]:
                        idx = body_text.find(marker)
                        if idx >= 0:
                            return body_text[idx : idx + 3000][:5000]

            logger.warning("[智联] Could not extract JD from HTML")
            return ""

        except Exception as e:
            logger.warning(f"[智联] HTTP JD fetch error: {e}")
            return ""


async def zhilian_login(
    cookie_path: str = "data/cookies/zhilian.json",  # noqa: ARG001 -- kept for plugin compat
    timeout_s: int = 180,
) -> bool:
    """智联招聘 browser-based login: opens headed Chromium for manual login.

    The user manually logs in on zhaopin.com. After login, cookies are
    persisted in the browser profile (data/zhilian_browser_profile/).
    Subsequent searches reuse the profile -- no cookie export needed.

    Returns True if login was detected, False on timeout.
    """
    from agent_core.platforms.zhilian_browser import zhilian_browser_login

    profile_dir = "data/zhilian_browser_profile"
    print("\n[智联] 启动浏览器到 https://www.zhaopin.com/")
    print(f"[智联] 请在 {timeout_s} 秒内手动登录（扫码或账号密码）")
    print("[智联] 登录后 cookie 自动保存到浏览器 profile，后续搜索无需再次登录。")
    print(f"[智联] Profile 目录: {profile_dir} (已 gitignored)")
    print()

    return await zhilian_browser_login(profile_dir=profile_dir, timeout_s=timeout_s)


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Parse Zhilian salary strings via the shared cross-platform parser."""
    return parse_salary_text(text)
