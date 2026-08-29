"""Boss zhipin Playwright browser with persistent profile.

Why this exists (separate from playwright_jd.py):
  Boss's job-detail page (/job_detail/{id}.html) redirects to an anti-bot
  security challenge under a NON-persistent context with injected cookies
  (see [[boss-detail-antibot-redirect]]). Boss detects the
  fresh-context + injected-cookie session as suspicious.

  A persistent browser context (user_data_dir) holds the FULL logged-in
  session including localStorage, sessionStorage, IndexedDB fingerprint
  tokens that Boss's bot manager checks. After a ONE-TIME manual login in
  the headed browser, subsequent headless fetches reuse that real session
  and bypass the security challenge.

Architecture:
  BossBrowser — singleton persistent Chromium context, same pattern as
                zhilian_browser.ZhilianBrowser. login() opens the homepage
                for manual login; search/fetch_jd reuse the saved session.

Usage:
  # one-time login (headed, user logs in manually)
  python -m agent_core.platforms.boss_browser login

  # then fetch JDs (can be headless after login is saved)
  from agent_core.platforms.boss_browser import fetch_jd, get_browser
  browser = await get_browser()
  jd = await fetch_jd("https://www.zhipin.com/job_detail/xxx.html")
"""

from __future__ import annotations

import asyncio
import atexit
import logging
from pathlib import Path
from typing import Any

from agent_core.platforms.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = "data/boss_browser_profile"

# Anti-detection init script — shared definition lives in playwright_jd.py
from agent_core.platforms.playwright_jd import _ANTI_DETECTION_SCRIPT  # noqa: E402

# CSS selectors for the JD container on /job_detail/ pages. First match wins.
# These are the containers observed on the live Boss detail page after login.
_JD_SELECTORS = [
    ".job-detail .job-sec-text",
    ".job-sec-text",
    ".job-detail-section .text",
    ".text",
    "[class*='job-detail'] [class*='content']",
    ".job-detail",
]

# Body-text heading markers for the fallback slicer (when no selector hits).
_JD_HEADING_MARKERS = ["岗位职责", "职位描述", "任职要求", "岗位要求"]
_TRAILING_MARKERS = [
    "举报",
    "投诉",
    "APP下载",
    "下载APP",
    "扫码下载",
    "看了该职位的人还看了",
    "猜你喜欢",
    "相似职位",
    "友情链接",
]


class BossBrowser:
    """Persistent Chromium context for Boss zhipin.

    Holds login session across runs via user_data_dir. After one manual
    login, headless fetches reuse the saved session.
    """

    def __init__(self, profile_dir: str | Path = DEFAULT_PROFILE_DIR):
        self._profile_dir = Path(profile_dir)
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Any = None
        self._context: Any = None

    async def _ensure_browser(self, headless: bool = False) -> None:
        """Lazy-init the persistent browser context.

        If a context already exists, verifies it is still alive; re-launches
        on crash (GPU process death, SingletonLock races, anti-bot kill).
        """
        if self._context is not None:
            try:
                if self._context.browser and self._context.browser.is_connected():
                    return
                logger.warning("[BossBrowser] context dead; re-launching")
            except Exception as exc:
                logger.warning("[BossBrowser] liveness check failed (%s); re-launching", exc)
            await self._teardown_context()

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            ) from None

        self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=headless,
            args=launch_args,
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        await self._context.add_init_script(_ANTI_DETECTION_SCRIPT)
        logger.info("[BossBrowser] launched (headless=%s, profile=%s)", headless, self._profile_dir)

    async def _teardown_context(self) -> None:
        """Best-effort teardown of a dead context + remove stale lock files."""
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        from agent_core.platforms.browser_utils import remove_stale_lock_files

        remove_stale_lock_files(self._profile_dir)

    async def login(self, timeout_s: int = 300) -> bool:
        """Open Boss homepage for manual login.

        The user manually logs in (QR code or phone) in the headed browser.
        After login, the session is persisted in the profile dir for
        subsequent headless fetches.

        Args:
            timeout_s: Seconds to wait for login (Boss QR scan can be slow)

        Returns:
            True if login window opened and session detected
        """
        await self._ensure_browser(headless=False)
        page = await self._context.new_page()
        try:
            await page.goto("https://www.zhipin.com/", wait_until="domcontentloaded")
            print("\n[Boss] 浏览器已打开 https://www.zhipin.com/")
            print(f"[Boss] 请在浏览器中手动登录（{timeout_s} 秒内）：")
            print("[Boss]   - 扫码登录 或 手机号登录 均可")
            print("[Boss]   - 登录后窗口可关闭，会话自动保存到 profile")
            print()

            # Poll for the wt2/wbg/zp_at session cookies (persistent profile keeps them)
            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                cookies = await self._context.cookies()
                names = {c["name"] for c in cookies}
                # wt2 + wbg are the core Boss session cookies; zp_at is the
                # newer token. Presence of any 2 of these = logged in.
                session_hits = len(names & {"wt2", "wbg", "zp_at", "boss_token"})
                if session_hits >= 2:
                    print("[Boss] ✅ 登录成功，会话已保存到 profile。")
                    return True
                await asyncio.sleep(2)

            print(f"[Boss] ❌ 登录超时（{timeout_s} 秒）")
            return False
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def fetch_jd(self, url: str, headless: bool = False, timeout_ms: int = 25000) -> str:
        """Fetch full JD text by rendering a Boss job-detail page.

        Uses the persistent logged-in profile, so the anti-bot security
        challenge is bypassed (session fingerprint is real).

        Args:
            url: Boss job-detail URL (https://www.zhipin.com/job_detail/{id}.html)
            headless: Run headless after login is saved (default False —
                      headed is safer against anti-bot even post-login)
            timeout_ms: Max wait for page load

        Returns:
            JD text (truncated to 5000 chars) or "" on any failure.
        """
        if not url or not url.startswith("http"):
            return ""

        _CONTEXT_CLOSED_MSGS = (
            "Target page, context or browser has been closed",
            "Browser has been closed",
            "Browser closed",
        )
        _LAUNCH_FAIL_MSGS = (
            "Target page, context or browser has been closed",
            "Failed to launch",
            "Another instance",
            "SingletonLock",
        )

        for attempt in range(2):
            try:
                await self._ensure_browser(headless=headless)
            except Exception as e:
                if any(p in str(e) for p in _LAUNCH_FAIL_MSGS) and attempt == 0:
                    logger.warning("[BossBrowser] launch failed (%s) — retrying", e)
                    await self._teardown_context()
                    continue
                logger.error("[BossBrowser] _ensure_browser failed: %s", e)
                return ""

            try:
                page = await self._context.new_page()
            except Exception as e:
                if any(p in str(e) for p in _CONTEXT_CLOSED_MSGS) and attempt == 0:
                    logger.warning("[BossBrowser] context dead on new_page — retrying")
                    await self._teardown_context()
                    continue
                logger.error("[BossBrowser] new_page failed: %s", e)
                return ""

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                # If redirected to the security challenge page, the session
                # isn't logged in — bail out so the user knows to re-login.
                if "passport/zp/security" in page.url:
                    logger.error(
                        "[BossBrowser] redirected to anti-bot security page — "
                        "session not logged in. Run: python -m agent_core.platforms.boss_browser login"
                    )
                    return ""

                # Wait for JS to render the JD. Boss detail pages are SPA-like.
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)  # extra settle for late-rendered JD

                # Try platform selectors first
                jd_text = ""
                for sel in _JD_SELECTORS:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            text = (await el.inner_text()).strip()
                            if text and len(text) > 20:
                                jd_text = text
                                break
                    except Exception:
                        continue

                # Fallback: body innerText + slice from JD heading
                if not jd_text:
                    try:
                        body_text = (await page.inner_text("body")).strip()
                    except Exception:
                        body_text = ""
                    if body_text:
                        jd_text = _slice_jd_from_body(body_text)
                        if not jd_text and len(body_text) >= 100:
                            jd_text = body_text

                if jd_text and len(jd_text) > 5000:
                    jd_text = jd_text[:5000]
                return jd_text
            except Exception as e:
                if any(p in str(e) for p in _CONTEXT_CLOSED_MSGS) and attempt == 0:
                    logger.warning("[BossBrowser] nav error (%s) — retrying", e)
                    await self._teardown_context()
                    continue
                logger.error("[BossBrowser] fetch error for %s: %s", url, e)
                return ""
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        logger.error("[BossBrowser] retries exhausted for %s", url)
        return ""

    async def close(self) -> None:
        await self._teardown_context()
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        logger.info("[BossBrowser] closed")


def _slice_jd_from_body(body_text: str) -> str:
    """Slice JD text from page body when no CSS selector matches.

    Finds first JD heading marker, slices forward to first trailing marker.
    """
    start = -1
    for m in _JD_HEADING_MARKERS:
        idx = body_text.find(m)
        if idx >= 0:
            start = idx
            break
    if start < 0:
        return ""
    tail = body_text[start:]
    for m in _JD_HEADING_MARKERS:
        if tail.startswith(m):
            tail = tail[len(m) :]
            break
    tail = tail.lstrip("：: \n")
    end = len(tail)
    for m in _TRAILING_MARKERS:
        idx = tail.find(m)
        if idx >= 0 and idx < end:
            end = idx
    return tail[:end].strip()


# ── module-level singleton ──────────────────────────────────────────────
_manager = BrowserManager()
_browser_lock = asyncio.Lock()
_cleanup_registered = False


async def get_browser(profile_dir: str | Path = DEFAULT_PROFILE_DIR) -> BossBrowser:
    """Return the singleton BossBrowser instance, launching Chromium eagerly."""
    global _cleanup_registered
    async with _browser_lock:
        browser = _manager.browser
        if browser is None:
            browser = BossBrowser(profile_dir=profile_dir)
            _manager.set_browser(browser)
        if not _cleanup_registered:
            _cleanup_registered = True
            _register_cleanup()
        # eager init so concurrent callers don't race
        try:
            await browser._ensure_browser(headless=False)
        except Exception as e:
            # stale lock files — retry once
            logger.warning("[BossBrowser] get_browser init failed (%s) — retrying", e)
            await browser._teardown_context()
            await browser._ensure_browser(headless=False)
    return browser


async def close_browser() -> None:
    async with _browser_lock:
        await _manager.close_browser()


async def fetch_jd(url: str, headless: bool = False) -> str:
    """Convenience: fetch JD using the singleton browser."""
    browser = await get_browser()
    return await browser.fetch_jd(url, headless=headless)


async def login(timeout_s: int = 300) -> bool:
    """Convenience: open browser for manual login."""
    browser = await get_browser()
    return await browser.login(timeout_s=timeout_s)


def _register_cleanup() -> None:
    import sys

    def _sync_cleanup() -> None:
        inst = _manager.browser
        if inst is None:
            return
        _manager.clear_browser()
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(inst.close())
            loop.close()
        except Exception:
            pass

    atexit.register(_sync_cleanup)
    try:
        import signal

        if sys.platform == "win32":
            try:
                signal.signal(signal.SIGTERM, lambda *_: _sync_cleanup())
            except Exception:
                pass
        signal.signal(signal.SIGINT, lambda *_: _sync_cleanup())
    except Exception:
        pass


# ── CLI: python -m agent_core.platforms.boss_browser login ──────────────
if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    if len(sys.argv) < 2 or sys.argv[1] not in ("login", "fetch"):
        print("Usage:")
        print("  python -m agent_core.platforms.boss_browser login    # one-time manual login")
        print("  python -m agent_core.platforms.boss_browser fetch <url>  # fetch one JD")
        sys.exit(1)

    if sys.argv[1] == "login":
        ok = asyncio.run(login(timeout_s=300))
        asyncio.run(close_browser())
        sys.exit(0 if ok else 1)

    if sys.argv[1] == "fetch":
        if len(sys.argv) < 3:
            print("Usage: python -m agent_core.platforms.boss_browser fetch <url>")
            sys.exit(1)
        url = sys.argv[2]
        jd = asyncio.run(fetch_jd(url, headless=False))
        print(f"JD_LEN={len(jd)}")
        print("JD_PREVIEW=" + (jd[:500] if jd else "(empty)"))
        asyncio.run(close_browser())
