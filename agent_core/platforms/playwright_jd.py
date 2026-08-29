"""Playwright-based full JD fetcher shared across platforms.

Why this exists:
  Boss and Liepin's HTTP-based fetch_full_jd both fail on a large fraction of
  jobs because the detail pages are JS-rendered and/or anti-bot protected.
  Playwright with a real Chromium + injected cookies renders the page and
  lets us read the JD text from the live DOM, bypassing the static-HTTP
  limitations.

Design:
  - One module-level singleton browser (Chromium, headless=False by default
    — headed mode is more resistant to anti-bot per [[akamai-bot-manager-bypass]]).
  - Cookies are injected per-platform from the existing cookie JSON files
    (data/cookies/boss_zhipin.json, data/cookies/liepin.json). No persistent
    profile needed for the first iteration — keeps the change small.
  - Per-platform CSS selectors extract the JD container text after render.
  - Falls back to <body> innerText if the platform-specific selector misses.

Usage:
  from agent_core.platforms.playwright_jd import fetch_jd_playwright
  jd_text = await fetch_jd_playwright(
      url="https://www.zhipin.com/job_detail/xxx.html",
      platform="boss_zhipin",
      cookie_path="data/cookies/boss_zhipin.json",
  )
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent_core.platforms.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

# Per-platform JD container selectors. First match wins.
# These are the most stable containers observed on each platform's detail page.
PLATFORM_SELECTORS: dict[str, list[str]] = {
    "boss_zhipin": [
        ".job-detail-section .job-sec-text",
        ".job-sec-text",
        ".text",
        "[class*='job-detail']",
    ],
    "liepin": [
        # /a/ path pages: JD lives under a "职位介绍" heading in a generic
        # .content block. The more specific selectors above rarely match on
        # /a/ pages, so we keep them as fallbacks and rely on the body-text
        # extractor below to slice from "职位介绍" onward.
        ".job-intro-container .content",
        ".job-description",
        ".content-text",
        "[class*='job-detail-content']",
        ".job-main .content",
    ],
    "zhilian": [
        # 智联招聘 JD 页面结构
        ".describtion__detail-content",
        ".job-description",
        "[class*='description']",
        "[class*='job-detail']",
    ],
    "byd": [
        # 比亚迪招聘 JD 页面结构
        ".job-detail-content",
        ".job-description",
        "[class*='detail']",
        "[class*='description']",
    ],
    "naura": [
        # 北方华创 JD 页面结构
        ".job-detail",
        ".job-description",
        "[class*='detail']",
    ],
    "netease": [
        # 网易招聘 JD 页面结构
        ".job-detail-content",
        ".job-desc",
        "[class*='detail']",
    ],
    "tencent": [
        # 腾讯招聘 JD 页面结构
        ".job-detail-content",
        ".job-desc",
        "[class*='detail']",
    ],
    "yofc": [
        # 光迅科技 JD 页面结构
        ".job-detail",
        ".job-description",
        "[class*='detail']",
    ],
}

# Domains each platform's cookies apply to (for cookie injection).
PLATFORM_COOKIE_DOMAINS: dict[str, list[str]] = {
    "boss_zhipin": [".zhipin.com", "zhipin.com"],
    "liepin": [".liepin.com", "liepin.com"],
    "zhilian": [".zhaopin.com", "zhaopin.com", "jobs.zhaopin.com"],
    "byd": [".byd.com", "job.byd.com"],
    "naura": [".naura.com", "naura.com"],
    "netease": [".163.com", "hr.163.com"],
    "tencent": [".qq.com", "tencent.com"],
    "yofc": [".yofc.com", "yofc.com"],
}

# Anti-detection init script (same as zhilian_browser.py)
_ANTI_DETECTION_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = { runtime: {} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({state: Notification.permission}) :
        originalQuery(parameters)
    );
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
"""

_browser_instance: Any = None
_browser_lock = asyncio.Lock()
_cleanup_registered = False

# Idle auto-close: after a fetch, if no new fetch arrives within this window,
# the shared browser is closed so a headed Chromium isn't left running
# indefinitely (occupying resources + holding cookies). Any new fetch
# re-launches it.
#
# Two mechanisms, both cheap:
#   1. A timestamp is recorded after each fetch. At the start of the next
#      fetch, if the browser is still alive but idle beyond the window, it is
#      closed before re-launching (this covers callers that run without a
#      running event loop, e.g. serve.py's new_event_loop + run_until_complete).
#   2. When there IS a running event loop, a one-shot timer task is created to
#      proactively close the browser at the deadline (true "60s idle -> close").
_IDLE_CLOSE_SECONDS = 60
_idle_manager = BrowserManager(idle_close_seconds=_IDLE_CLOSE_SECONDS)
_idle_task: asyncio.Task | None = None


def _cancel_idle_timer() -> None:
    global _idle_task
    if _idle_task is not None:
        _idle_task.cancel()
        _idle_task = None


def _schedule_idle_close() -> None:
    """Arm the idle close: record the deadline, and if a loop is running,
    schedule a proactive close task."""
    global _idle_task
    _idle_manager.touch()
    _cancel_idle_timer()
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # no running loop — deadline will be checked on next fetch

    async def _after_idle() -> None:
        await asyncio.sleep(_IDLE_CLOSE_SECONDS)
        if _browser_instance is not None:
            logger.info("[PlaywrightJD] idle timeout reached, closing browser")
            await close_browser()

    _idle_task = asyncio.create_task(_after_idle())


def _idle_expired() -> bool:
    """True if the browser has been idle (no fetch) beyond the window."""
    return _idle_manager.idle_expired()


def _load_cookies_for_playwright(cookie_path: str) -> list[dict]:
    """Load cookies from a browser-exported JSON file and convert to
    Playwright's add_cookies format (shared implementation in cookie_utils)."""
    from agent_core.platforms.cookie_utils import load_cookies_for_playwright

    if not Path(cookie_path).exists():
        logger.warning(f"[PlaywrightJD] cookie file not found: {cookie_path}")
    return load_cookies_for_playwright(cookie_path)


async def _ensure_browser(headless: bool = False) -> Any:
    """Lazy-init a shared Chromium browser context (non-persistent).

    Uses a single browser + context pair so multiple fetches reuse the same
    Chromium process (avoids the launch overhead per call). Cookies are
    added per-platform at fetch time via add_cookies on this context.
    """
    global _browser_instance, _cleanup_registered
    async with _browser_lock:
        if _browser_instance is not None:
            # Liveness check — browser.is_connected() can be True while the
            # context is dead (e.g. after taskkill). Verify by probing the
            # context with a cheap operation.
            try:
                b = _browser_instance["browser"]
                ctx = _browser_instance["context"]
                if b and b.is_connected():
                    # Probe: try to access an existing page or cookies
                    _pages = ctx.pages
                    return _browser_instance
                logger.warning("[PlaywrightJD] browser dead, re-launching")
            except Exception:
                logger.warning("[PlaywrightJD] liveness check failed, re-launching")
            # teardown dead instance
            try:
                await _browser_instance["context"].close()
            except Exception:
                pass
            try:
                await _browser_instance["browser"].close()
            except Exception:
                pass
            _browser_instance = None

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            ) from None

        pw = await async_playwright().start()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        browser = await pw.chromium.launch(headless=headless, args=launch_args)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        await context.add_init_script(_ANTI_DETECTION_SCRIPT)
        _browser_instance = {
            "playwright": pw,
            "browser": browser,
            "context": context,
        }

        if not _cleanup_registered:
            _cleanup_registered = True
            import atexit

            def _sync_cleanup() -> None:
                global _browser_instance
                inst = _browser_instance
                if inst is None:
                    return
                _browser_instance = None
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(_async_close(inst))
                    loop.close()
                except Exception:
                    pass

            async def _async_close(inst):
                try:
                    await inst["context"].close()
                    await inst["browser"].close()
                    await inst["playwright"].stop()
                except Exception:
                    pass

            atexit.register(_sync_cleanup)

        return _browser_instance


async def fetch_jd_playwright(
    url: str,
    platform: str,
    cookie_path: str,
    headless: bool = False,
    timeout_ms: int = 20000,
) -> str:
    """Fetch full JD text by rendering the job detail page in Playwright.

    Args:
        url: Job detail page URL (job.lid).
        platform: One of PLATFORM_SELECTORS keys (boss_zhipin / liepin).
        cookie_path: Path to the platform's cookie JSON file.
        headless: Run headless (more detectable; default False).
        timeout_ms: Max wait for page load + selector.

    Returns:
        JD text (truncated to 5000 chars), or "" on any failure.
    """
    if not url or not url.startswith("http"):
        logger.debug(f"[PlaywrightJD] invalid url: {url}")
        return ""

    selectors = PLATFORM_SELECTORS.get(platform)
    if not selectors:
        logger.warning(f"[PlaywrightJD] unknown platform: {platform}")
        return ""

    # A new fetch arrived — cancel any pending idle close so the browser stays up.
    _cancel_idle_timer()
    # If the browser was idle beyond the window, close it before re-launching
    # (covers callers without a running loop where no timer task was created).
    if _idle_expired() and _browser_instance is not None:
        logger.info("[PlaywrightJD] idle window passed since last fetch, closing stale browser")
        await close_browser()

    try:
        inst = await _ensure_browser(headless=headless)
    except Exception as e:
        logger.error(f"[PlaywrightJD] browser init failed: {e}")
        return ""

    context = inst["context"]

    # Inject cookies for this platform (idempotent — Playwright dedupes by name+domain+path)
    cookies = _load_cookies_for_playwright(cookie_path)
    if cookies:
        # Filter to this platform's domains to avoid polluting context with
        # other platforms' cookies.
        domains = PLATFORM_COOKIE_DOMAINS.get(platform, [])
        filtered = (
            [c for c in cookies if any(d in c.get("domain", "") for d in domains)]
            if domains
            else cookies
        )
        if filtered:
            try:
                await context.add_cookies(filtered)
            except Exception as e:
                logger.warning(f"[PlaywrightJD] add_cookies failed: {e}")

    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.warning(f"[PlaywrightJD] goto failed for {url}: {e}")
            return ""

        # Wait briefly for JS to render the JD container, then try each selector.
        jd_text = ""
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass  # networkidle may not fire on some pages; continue anyway

        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and len(text) > 20:
                        jd_text = text
                        break
            except Exception:
                continue

        # Fallback: full body innerText, then slice to the JD region if the
        # page has a "职位介绍" / "岗位职责" heading (common on Liepin /a/
        # pages where no platform selector matches).
        if not jd_text:
            try:
                body_text = (await page.inner_text("body")).strip()
            except Exception:
                body_text = ""
            if body_text:
                jd_text = _slice_jd_from_body(body_text, platform)
                if not jd_text and len(body_text) >= 100:
                    # last resort: return the whole body text
                    jd_text = body_text

        if jd_text and len(jd_text) > 5000:
            jd_text = jd_text[:5000]
        return jd_text
    finally:
        try:
            await page.close()
        except Exception:
            pass
        # Fetch done — arm the idle close. Any next fetch cancels it.
        _schedule_idle_close()


async def close_browser() -> None:
    """Close the shared browser singleton."""
    global _browser_instance, _idle_task
    _cancel_idle_timer()
    _idle_manager.clear_browser()
    async with _browser_lock:
        if _browser_instance is not None:
            inst = _browser_instance
            _browser_instance = None
            try:
                await inst["context"].close()
                await inst["browser"].close()
                await inst["playwright"].stop()
            except Exception:
                pass
            logger.info("[PlaywrightJD] browser closed")


# JD section heading markers per platform. On Liepin /a/ pages the JD sits
# under a "职位介绍" heading; on Boss under "岗位职责". We slice the body
# innerText from the first such heading to the start of the trailing nav
# chrome ("举报", "投诉建议", "APP下载", etc.) to recover the JD when no
# CSS selector matches.
_JD_HEADING_MARKERS: dict[str, list[str]] = {
    "liepin": ["职位介绍", "岗位职责", "职位描述", "任职要求"],
    "boss_zhipin": ["岗位职责", "职位描述", "任职要求"],
    "zhilian": ["岗位职责", "职位描述", "任职要求", "工作职责", "岗位要求"],
}

# Trailing chrome markers that signal end-of-JD. The slice stops at the
# first of these encountered after the heading.
_TRAILING_MARKERS: list[str] = [
    "举报",
    "投诉建议",
    "APP下载",
    "猎聘APP",
    "下载APP",
    "扫码下载",
    "类似职位",
    "看了该职位的人还看了",
    "猜你喜欢",
]


def _slice_jd_from_body(body_text: str, platform: str) -> str:
    """Recover JD text from page body innerText when no CSS selector matches.

    Finds the first JD heading marker, then slices forward until the first
    trailing-chrome marker (or end of text). Returns "" if no heading found.
    """
    markers = _JD_HEADING_MARKERS.get(platform, [])
    start = -1
    for m in markers:
        idx = body_text.find(m)
        if idx >= 0:
            start = idx
            break
    if start < 0:
        return ""
    # Slice from the heading onward
    tail = body_text[start:]
    # Trim the heading line itself
    for m in markers:
        if tail.startswith(m):
            tail = tail[len(m) :]
            break
    tail = tail.lstrip("：: \n")
    # Find the first trailing marker
    end = len(tail)
    for m in _TRAILING_MARKERS:
        idx = tail.find(m)
        if idx >= 0 and idx < end:
            end = idx
    jd = tail[:end].strip()
    return jd
