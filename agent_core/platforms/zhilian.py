"""智联招聘 platform adapter using direct HTTP API.

API discovery (2026-06-21, endpoint corrected 2026-06-21):
  Primary endpoint: POST https://fe-api.zhaopin.com/c/i/search/positions
  JSON body: {S_SOU_FULL_INDEX, S_SOU_WORK_CITY, pageSize, pageIndex,
    actionid, cvNumber, eventScenario, anonymous, resumeNumber,
    clickFilterBlackCompany, sortType, platform, version}
  Response shape: {code, apiCode, data: {count, list: [{name, companyName,
    salary60, education, workingExp, workCity, cityDistrict, cityId,
    positionURL, number, companySize, industryName, workType, publishTime,
    jobDetailData: {position: {base: {positionName, salary, education,
    positionWorkingExp, workType, ...}, desc: {description, ...},
    workLocation: {address, ...}}}, ...}]}}
  Required headers: origin, referer (zhaopin.com), x-zp-action-id (UUID),
    x-zp-business-system: 1, x-zp-page-code: 4019, x-zp-platform: 13
  Anti-bot: GET /c/i/sou always returns count=0 (Akamai-protected).
    POST /c/i/search/positions works with valid cookies + x-zp-* headers.

Status: Live API confirmed working 2026-06-21. POST /c/i/search/positions
  returns real jobs with valid cookies and x-zp-* headers.
"""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path

from agent_core.platforms.base import Job, PlatformAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://www.zhaopin.com"
SEARCH_URL = "https://sou.zhaopin.com"
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


def _session_cookie_valid(cookies: list[dict]) -> bool:
    """True if 智联 session cookies are present and not expired.

    Session indicators: FSSBBIl1UgzbN7NS (www.zhaopin.com, httpOnly, secure),
    x-zp-client-id (.zhaopin.com, secure), zp_passport_deepknow_sessionId.
    """
    now = time.time()
    session_names = {"FSSBBIl1UgzbN7NS", "FSSBBIl1UgzbN7NT"}
    found = False
    for c in cookies:
        if c.get("name") in session_names:
            found = True
            exp = c.get("expires") or c.get("expirationDate", -1)
            if isinstance(exp, int | float) and exp > 0 and exp <= now:
                return False  # Explicitly expired
    return found


def _notify_anti_bot(platform: str = "智联招聘") -> None:
    """Fire a toast + log when anti-bot challenge is triggered."""
    logger.warning(
        f"[智联] Anti-bot challenge triggered ({platform}) — "
        "API returns 0 results despite valid request"
    )
    try:
        from agent_core.notify.windows_toast import notify_anti_bot

        notify_anti_bot(platform)
    except Exception:
        logger.debug("Anti-bot notify skipped")


def _notify_cookie_expired(platform: str = "智联招聘") -> None:
    """Fire a toast + log when the cookie is missing/expired/rejected."""
    logger.warning("[智联] Cookie missing or expired — re-login required")
    try:
        from agent_core.notify.windows_toast import notify_cookie_expired

        notify_cookie_expired(platform)
    except Exception:
        logger.debug("Cookie-expired notify skipped")


class ZhilianAdapter(PlatformAdapter):
    name = "zhilian"

    def __init__(self, rate_limit_seconds: int | None = None):
        self._rate_limit_seconds = rate_limit_seconds if rate_limit_seconds is not None else 2.0
        self._ANTI_BOT_BACKOFF_SECONDS = (
            rate_limit_seconds if rate_limit_seconds is not None else 300
        )

    async def search(
        self,
        keywords: list[str],
        location: str,
        cookie_path: str | None = None,
        headless: bool = False,
        rate_limit_seconds: int | None = None,
    ) -> list[Job]:
        """Search 智联招聘 via direct HTTP API.

        Uses fe-api.zhaopin.com/c/i/search/positions (POST). headless is ignored.

        Anti-bot note: When the API returns code=200 but count=0,
        cookies are likely stale. The adapter logs a warning and returns [].
        """
        if rate_limit_seconds is not None:
            self._rate_limit_seconds = rate_limit_seconds

        cookies = _load_cookies(cookie_path)
        if not cookies:
            logger.warning(
                f"[智联] No cookie at {cookie_path}; "
                f"run `job-agent import-cookies <file> zhilian --domain zhaopin.com` first"
            )
            _notify_cookie_expired()
            return []
        if not _session_cookie_valid(cookies):
            _notify_cookie_expired()
            return []

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        city_code = CITY_CODES.get(location, "0")

        jobs: list[Job] = []
        for keyword in keywords[:2]:
            keyword_jobs = await self._search_keyword_api(
                keyword, city_code, cookie_str, rate_limit_seconds
            )
            jobs.extend(keyword_jobs)
            await asyncio.sleep(2)  # inter-keyword rate limit

        logger.info(f"[智联] {len(jobs)} jobs total for keywords {keywords[:2]}")
        return jobs

    def _build_headers(self, cookie_str: str) -> tuple[dict[str, str], str]:
        """Build headers matching browser POST to /c/i/search/positions.

        x-zp-action-id is a random UUID per request (matches actionid in body).
        sec-ch-ua-* headers are omitted -- not required by the API.
        """
        action_id = str(uuid.uuid4())
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": BASE_URL,
            "Pragma": "no-cache",
            "Referer": f"{BASE_URL}/",
            "x-zp-action-id": action_id,
            "x-zp-business-system": "1",
            "x-zp-page-code": "4019",
            "x-zp-platform": "13",
            "Cookie": cookie_str,
        }, action_id

    async def _search_keyword_api(
        self,
        keyword: str,
        city_code: str,
        cookie_str: str,
        rate_limit_seconds: float | None = None,
    ) -> list[Job]:
        """Call 智联 POST /c/i/search/positions for one keyword.

        Returns jobs list (empty if anti-bot blocks). The POST endpoint
        requires x-zp-* headers and valid session cookies. GET /c/i/sou
        is Akamai-protected and always returns count=0.
        """
        import urllib.error
        import urllib.request

        headers, action_id = self._build_headers(cookie_str)

        body = {
            "S_SOU_FULL_INDEX": keyword,
            "S_SOU_WORK_CITY": city_code,
            "order": 0,
            "actionid": action_id,
            "pageSize": 20,
            "pageIndex": 1,
            "eventScenario": "pcSearchedSouSearch",
            "anonymous": 0,
            "clickFilterBlackCompany": False,
            "sortType": "DEFAULT",
            "platform": 13,
            "version": "0.0.0",
        }
        body_bytes = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            API_SEARCH,
            data=body_bytes,
            headers=headers,
            method="POST",
        )

        def _fetch() -> bytes:
            with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310
                return r.read()

        try:
            raw = await asyncio.to_thread(_fetch)
            obj = json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            logger.error(f"[智联] API HTTP {e.code} for '{keyword}': {e.reason}")
            _notify_cookie_expired()
            return []
        except Exception as e:
            logger.error(f"[智联] API error for '{keyword}': {e}")
            return []

        # Check response
        code = obj.get("code")
        api_code = obj.get("apiCode", 0)
        data = obj.get("data", {})
        total_count = data.get("count", 0)
        items = data.get("list", [])

        if code != 200 or api_code != 200:
            msg = obj.get("message", "")
            sd = data.get("statusDescription", "")
            logger.warning(
                f"[智联] API code={code} apiCode={api_code} msg={msg} statusDesc={sd}"
                f" for '{keyword}'"
            )
            _notify_cookie_expired()
            return []

        if total_count == 0:
            # code=200 but no data — stale or missing CAPTCHA cookie
            logger.warning(
                f"[智联] API returned count=0 for '{keyword}' "
                "(cookie may be stale / CAPTCHA needed). "
                "Try re-exporting cookies after visiting sou.zhaopin.com in browser "
                "and solving the CAPTCHA."
            )
            _notify_anti_bot()
            await asyncio.sleep(self._ANTI_BOT_BACKOFF_SECONDS)
            return []

        if not items and total_count > 0:
            # count>0 but list empty — true anti-bot soft block
            logger.warning(
                f"[智联] count={total_count} but list empty for '{keyword}' "
                "(anti-bot soft block likely)"
            )
            _notify_anti_bot()
            await asyncio.sleep(self._ANTI_BOT_BACKOFF_SECONDS)
            return []

        jobs: list[Job] = []
        for item in items:
            try:
                jobs.append(self._api_item_to_job(item))
            except Exception as e:
                logger.debug(f"[智联] Skip item: {e}")
                continue

        logger.info(f"[智联] '{keyword}': {len(jobs)} jobs (total={total_count})")
        return jobs

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


async def zhilian_login(
    cookie_path: str = "data/cookies/zhilian.json",
    timeout_s: int = 180,  # noqa: ARG001 -- signature required by plugin system
) -> bool:
    """智联招聘 has anti-bot protection that blocks automated browsers
    (the sou.zhaopin.com page returns "Security Verification"). This function
    guides the user through the manual cookie-export flow instead. Always returns
    False (no automated cookie was obtained).
    """
    export_path = Path(cookie_path).parent / "zhilian_export.json"
    print("\n[智联] 自动登录不可行（智联有 Akamai/CDN 反爬，Playwright 会被拦截）。")
    print("请按手动流程获取 cookie：")
    print("  1. 在日常 Chrome 访问 https://sou.zhaopin.com/ 并手动通过人机验证")
    print("  2. 用 Cookie-Editor 扩展导出 zhaopin.com 的全部 cookie 为 JSON")
    print("     （关键 cookie：FSSBBIl1UgzbN7NS、x-zp-client-id）")
    print(f"  3. 保存为 {export_path}")
    print(f"  4. 运行: job-agent import-cookies {export_path} zhilian --domain zhaopin.com")
    print("")
    print("  API 概览（已确认）:")
    print("    搜索: POST https://fe-api.zhaopin.com/c/i/search/positions")
    print("    必带头: origin, referer, x-zp-action-id, x-zp-business-system,")
    print("           x-zp-page-code, x-zp-platform")
    print("    响应: {code, apiCode, data: {count, list: [{name, companyName, salary60," " ...}]}}")
    print("    反爬: GET /c/i/sou 被 Akamai 拦截，需用 POST 端点")
    return False


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Parse '15K-25K' or '8千-1.2万' into (min, max) in yuan.

    Supports K/k format (thousands) and 千/万 format.
    """
    if not text:
        return None, None

    # Remove spaces and normalize
    text = text.strip()

    # Check for 万 format (e.g., "1.2万-1.8万", "8千-1.2万")
    if "万" in text or "千" in text:
        import re

        nums = re.findall(r"(\d+(?:\.\d+)?)", text)
        multipliers: list[float] = []
        for part in re.split(r"[-~]", text):
            if "万" in part:
                m = re.search(r"(\d+(?:\.\d+)?)", part)
                if m:
                    multipliers.append(float(m.group(1)) * 10000)
            elif "千" in part:
                m = re.search(r"(\d+(?:\.\d+)?)", part)
                if m:
                    multipliers.append(float(m.group(1)) * 1000)
        if len(multipliers) >= 2:
            return int(multipliers[0]), int(multipliers[1])
        if len(multipliers) == 1:
            return int(multipliers[0]), None
        return None, None

    # K/k format (e.g., "15K-25K", "8k-12k", "15K以上")
    import re

    if "K" not in text and "k" not in text:
        # Try pure number format (e.g., "15000-25000")
        nums = re.findall(r"(\d+)", text)
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
        if len(nums) == 1:
            return int(nums[0]), None
        return None, None

    nums = re.findall(r"(\d+(?:\.\d+)?)", text)
    if len(nums) >= 2:
        return int(float(nums[0]) * 1000), int(float(nums[1]) * 1000)
    if len(nums) == 1:
        return int(float(nums[0]) * 1000), None
    return None, None
