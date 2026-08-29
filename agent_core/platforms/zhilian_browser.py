"""Zhilian Playwright browser helper: bypasses Akamai via real Chromium.

This module encapsulates Playwright browser management for zhilian.com searches.
The browser automatically handles Akamai Bot Manager token generation (MmEwMD,
c1K5tw0w6_) and sensor data, which cannot be reliably generated from static HTTP.

Architecture:
  ZhilianBrowser — manages persistent browser profile, navigates to search URL,
                    intercepts fe-api.zhaopin.com XHR responses, returns parsed
                    Job objects.

Singleton pattern:
  Uses a module-level lazy singleton (get_browser / close_browser) so that
  multiple search() calls reuse the SAME persistent Chromium context within
  one process.  This avoids the "Target page, context or browser has been
  closed" crash that occurs when launch_persistent_context is called twice
  on the same user_data_dir while Chrome lock files (SingletonLock, etc.)
  are still held by the previous instance.

Usage:
  browser = await get_browser(profile_dir="data/zhilian_browser_profile")
  jobs = await browser.search(keyword="AMR", city_code="489", headless=False)
  # ... more searches on the same browser ...
  await close_browser()  # or rely on atexit cleanup

Profile: Persistent browser profile saves login cookies across sessions.
  After manual login once, subsequent searches use the saved cookies.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from agent_core.platforms.browser_manager import BrowserManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton: one ZhilianBrowser per process
# ---------------------------------------------------------------------------
_manager = BrowserManager()
_browser_lock = asyncio.Lock()
_cleanup_registered: bool = False

# Zhilian search URL template
SOU_URL = "https://sou.zhaopin.com"


def _build_search_url(keyword: str, city_code: str = "0") -> str:
    """Build the sou.zhaopin.com search URL with proper URL encoding."""
    url = f"{SOU_URL}/?keyword={quote(keyword, safe='')}"
    if city_code and city_code != "0":
        url += f"&city={quote(city_code, safe='')}"
    return url


# Anti-detection init script injected into every page — shared definition
# lives in playwright_jd.py (same JS, formatted differently here historically).
from agent_core.platforms.base import parse_salary_text  # noqa: E402
from agent_core.platforms.playwright_jd import _ANTI_DETECTION_SCRIPT  # noqa: E402


class ZhilianBrowser:
    """Manages a persistent Playwright Chromium instance for zhilian.com.

    Uses persistent context (user_data_dir) so login cookies survive
    across sessions. The browser handles Akamai token generation automatically.
    """

    def __init__(self, profile_dir: str | Path = "data/zhilian_browser_profile"):
        self._profile_dir = Path(profile_dir)
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    async def _ensure_browser(self, headless: bool = False) -> None:
        """Lazy-init the persistent browser context.

        If a context already exists, verifies it is still alive (browser
        process hasn't crashed).  On Windows, headless Chromium can die
        from GPU process crashes, SingletonLock races, or Akamai
        challenges — this check catches those cases and re-launches.
        """
        if self._context is not None:
            # Verify the browser process is still alive
            try:
                if self._context.browser and self._context.browser.is_connected():
                    # Context is alive — but check if cookies survived.
                    # On first launch the profile may have been fresh/empty;
                    # we must restore from backup even when the context
                    # itself is healthy.
                    cookies = await self._context.cookies()
                    if any(c["name"] in ("at", "rt") for c in cookies):
                        return  # all good
                    logger.info(
                        "[智联Browser] Context alive but at/rt missing; restoring from backup"
                    )
                    await _restore_cookies(self._context, self._profile_dir)
                    return
                logger.warning(
                    "[智联Browser] Existing context found but browser is dead; re-launching"
                )
            except Exception as exc:
                logger.warning(
                    "[智联Browser] Existing context failed liveness check (%s); re-launching",
                    exc,
                )
            # Context is dead — tear down what's left and restart
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
        )
        await self._context.add_init_script(_ANTI_DETECTION_SCRIPT)

        # ── restore cookies from backup if profile has no session ──
        cookies = await self._context.cookies()
        has_session = any(c["name"] in ("at", "rt") for c in cookies)
        if not has_session:
            restored = await _restore_cookies(self._context, self._profile_dir)
            if restored:
                pass  # restored silently
            else:
                pass  # will need login

        logger.info(
            "Chromium launched (headless=%s, profile=%s)",
            headless,
            self._profile_dir,
        )

    async def _teardown_context(self) -> None:
        """Best-effort teardown of a dead/crashed context without throwing.

        Separate from close() because close() must be idempotent and
        safe to call externally.  This helper only cleans up internal
        state — it does NOT touch the singleton or atexit registrations.

        Also removes Chromium SingletonLock / SingletonSocket /
        SingletonCookie files that prevent re-launching
        launch_persistent_context on the same profile dir after a crash.
        """
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        # Don't stop self._playwright here — the new context can reuse it

        # Remove stale Chromium singleton lock files so re-launch succeeds.
        from agent_core.platforms.browser_utils import remove_stale_lock_files

        remove_stale_lock_files(self._profile_dir)

    async def search(
        self,
        keyword: str,
        city_code: str = "0",
        headless: bool = False,
        timeout_ms: int = 30000,
    ) -> list[dict]:
        """Search zhilian.com for a keyword and return raw job items.

        Navigates to sou.zhaopin.com with keyword/city params, waits for
        the fe-api XHR response, and returns the data.list items.

        Auto-recovers from browser crashes: if the shared Chromium process
        dies mid-flight (common on Windows headless), tears down the dead
        context, re-launches, and retries once.

        Args:
            keyword: Search keyword (e.g. "AMR", "Python")
            city_code: Zhilian city code ("0" = nationwide, "489" = Beijing)
            headless: Run browser headless (more detectable, use False)
            timeout_ms: Max wait for API response

        Returns:
            Raw job items from data.list (empty list if blocked/timeout)
        """
        _CONTEXT_CLOSED_MSGS = (
            "Target page, context or browser has been closed",
            "Browser has been closed",
            "Browser closed",
        )
        # launch_persistent_context failures after a crash (lock files, etc.)
        _LAUNCH_FAIL_MSGS = (
            "Target page, context or browser has been closed",
            "Browser has been closed",
            "Browser closed",
            "Failed to launch",
            "Another instance",
            "SingletonLock",
        )

        for attempt in range(2):
            # ── ensure browser is alive (may throw if launch fails) ──
            try:
                await self._ensure_browser(headless=headless)
            except Exception as e:
                msg = str(e)
                if any(pat in msg for pat in _LAUNCH_FAIL_MSGS) and attempt == 0:
                    logger.warning(
                        "[智联Browser] Launch/ensure failed (%s) — tearing down & retrying", e
                    )
                    await self._teardown_context()
                    continue
                logger.error("[智联Browser] _ensure_browser failed: %s", e)
                return []

            # ── create page ──
            try:
                page = await self._context.new_page()
            except Exception as e:
                msg = str(e)
                if any(pat in msg for pat in _CONTEXT_CLOSED_MSGS) and attempt == 0:
                    logger.warning(
                        "[智联Browser] Context dead on new_page() — tearing down & retrying"
                    )
                    await self._teardown_context()
                    continue
                logger.error("[智联Browser] new_page() failed: %s", e)
                return []

            intercepted: list[dict] = []

            async def _on_response(response):
                url = response.url
                if "fe-api.zhaopin.com" in url and "/search/positions" in url:
                    try:
                        body = await response.json()
                        intercepted.append(body)
                    except Exception:
                        logger.debug("[智联Browser] Failed to parse fe-api response")

            page.on("response", _on_response)

            try:
                # Build search URL: keyword + optional city filter (URL-encoded)
                search_url = _build_search_url(keyword, city_code)

                logger.info("[智联Browser] Navigating to %s", search_url)
                await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)

                # Wait for fe-api response to arrive
                deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
                while not intercepted:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        logger.warning("[智联Browser] Timeout waiting for fe-api response")
                        break
                    await asyncio.sleep(min(1.0, remaining))

            except Exception as e:
                msg = str(e)
                if any(pat in msg for pat in _CONTEXT_CLOSED_MSGS) and attempt == 0:
                    logger.warning(
                        "[智联Browser] Browser crashed mid-navigation — tearing down & retrying"
                    )
                    await self._teardown_context()
                    continue
                logger.error("[智联Browser] Navigation error: %s", e)
                return []
            finally:
                try:
                    await page.close()
                except Exception:
                    pass  # Page may already be closed if context died

            if not intercepted:
                return []

            # Extract data.list from the first successful response
            for resp in intercepted:
                code = resp.get("code")
                api_code = resp.get("apiCode", 0)
                data = resp.get("data", {})
                items = data.get("list", [])
                count = data.get("count", 0)

                if code == 200 and api_code == 200 and items:
                    logger.info(
                        "[智联Browser] '%s': %d items (total count=%d)",
                        keyword,
                        len(items),
                        count,
                    )
                    return items

                if code == 200 and count == 0:
                    logger.warning("[智联Browser] '%s': count=0 (possible anti-bot)", keyword)
                    return []

                if code == 200 and not items:
                    logger.warning(
                        "[智联Browser] '%s': count=%d but list empty (soft block)",
                        keyword,
                        count,
                    )
                    return []

            logger.warning("[智联Browser] '%s': no valid response found", keyword)
            return []

        # Exhausted retries
        logger.error("[智联Browser] '%s': all retries exhausted", keyword)
        return []

    async def login(self, timeout_s: int = 180) -> bool:
        """Open browser to zhilian.com login page for manual login.

        If valid session cookies (at + rt) already exist in the profile,
        skips browser launch entirely and reports \"already logged in\".
        Otherwise opens a headed Chromium window for manual login.

        Args:
            timeout_s: Seconds to wait for user to complete login

        Returns:
            True if login succeeded or was already active
        """
        # Check for existing session BEFORE launching browser
        await self._ensure_browser(headless=False)
        cookies = await self._context.cookies()
        has_at = any(c["name"] == "at" for c in cookies)
        has_rt = any(c["name"] == "rt" for c in cookies)
        if has_at and has_rt:
            print("\n[智联] ✅ 已登录（at/rt 有效），无需重复登录。")
            print("[智联] 如需重新登录，请先删除浏览器 profile 目录。")
            return True

        page = await self._context.new_page()
        try:
            await page.goto("https://www.zhaopin.com/", wait_until="domcontentloaded")
            print("\n[智联] 浏览器已打开 https://www.zhaopin.com/")
            print(f"[智联] 请在浏览器中手动登录（{timeout_s} 秒内）...")
            print("[智联] 登录后关闭浏览器窗口即可，cookie 会自动保存。\n")

            deadline = asyncio.get_event_loop().time() + timeout_s
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1)
                cookies = await self._context.cookies()
                has_at = any(c["name"] == "at" for c in cookies)
                has_rt = any(c["name"] == "rt" for c in cookies)
                if has_at and has_rt:
                    print("[智联] ✅ 登录成功，cookie 已保存并备份。")
                    await _backup_cookies(cookies, self._profile_dir)
                    return True

            print(f"[智联] ❌ 登录超时（{timeout_s} 秒）")
            return False
        finally:
            await page.close()

    async def close(self) -> None:
        """Close the browser and clean up resources."""
        await self._teardown_context()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("[智联Browser] Browser closed")


async def get_browser(
    profile_dir: str | Path = "data/zhilian_browser_profile",
    headless: bool = False,
) -> ZhilianBrowser:
    """Return the module-level singleton ZhilianBrowser instance.

    Multiple callers (e.g. pipeline stages for different directions) share
    the SAME persistent Chromium context.  This eliminates the race with
    Chrome profile lock files that caused the second launch_persistent_context
    to crash with "Target page, context or browser has been closed".

    The browser is fully initialized (Chromium launched) before this returns,
    guarded by asyncio.Lock so concurrent callers serialize on first launch.

    Retries once if launch_persistent_context fails (stale lock files, etc.).

    Thread/async-safe: protected by asyncio.Lock during first init.
    """
    global _cleanup_registered

    from agent_core.platforms.browser_utils import LAUNCH_FAIL_MARKERS

    async with _browser_lock:
        browser = _manager.browser
        if browser is None:
            browser = ZhilianBrowser(profile_dir=profile_dir)
            _manager.set_browser(browser)

        if not _cleanup_registered:
            _cleanup_registered = True
            _register_cleanup()

        # Eagerly initialize the browser inside the lock so concurrent
        # callers don't race on _ensure_browser() -> launch_persistent_context.
        # Retry once on launch failures (stale lock files after crash).
        for _attempt in range(2):
            try:
                await browser._ensure_browser(headless=headless)
                break
            except Exception as e:
                msg = str(e)
                if any(pat in msg for pat in LAUNCH_FAIL_MARKERS) and _attempt == 0:
                    logger.warning(
                        "[智联Browser] get_browser: launch failed (%s) — tearing down & retrying",
                        e,
                    )
                    await browser._teardown_context()
                    continue
                raise

    return browser


async def close_browser() -> None:
    """Close the singleton browser and release resources.

    Safe to call multiple times -- subsequent calls are no-ops.
    After this, get_browser() will create a fresh instance.
    """
    async with _browser_lock:
        await _manager.close_browser()
        logger.info("[智联Browser] Singleton browser closed")


def _register_cleanup() -> None:
    """Register cleanup hooks that run on normal process exit.

    Uses threading._register_atexit-like approach so cleanup fires
    before the event loop is torn down.  On Windows, also attempts
    to kill orphan Chrome processes that might hold profile locks.
    """
    import signal
    import sys

    def _sync_cleanup() -> None:
        """Best-effort synchronous cleanup from a non-async context."""
        inst = _manager.browser
        if inst is None:
            return
        _manager.clear_browser()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_async_cleanup_fire_and_forget(inst))
            else:
                loop.run_until_complete(inst.close())
        except Exception:
            logger.debug("[智联Browser] Cleanup: event loop unavailable, skipping")

    async def _async_cleanup_fire_and_forget(inst: ZhilianBrowser) -> None:
        try:
            await inst.close()
        except Exception:
            pass

    # atexit runs before event loop teardown on CPython
    atexit.register(_sync_cleanup)

    # Windows: also try to clean up on SIGTERM/SIGINT
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGTERM, lambda *_: _sync_cleanup())
        except Exception:
            pass
    try:
        signal.signal(signal.SIGINT, lambda *_: _sync_cleanup())
    except Exception:
        pass


def _parse_salary(text: str) -> tuple[int | None, int | None]:
    """Parse salary via the shared cross-platform parser (kept for API compat)."""
    return parse_salary_text(text)


async def _backup_cookies(cookies: list[dict], profile_dir: Path) -> None:
    """Backup cookies to a JSON file outside the browser profile.

    If the Chromium profile's Cookies file is later cleared (e.g. on
    Dashboard "clear data"), the backup can be used to re-inject the
    session.
    """
    backup_dir = Path("data/zhilian_cookies_backup")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "zhilian_cookies.json"
    try:
        backup_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("[智联Browser] Failed to backup cookies: %s", e)


async def _restore_cookies(context: Any, profile_dir: Path) -> bool:
    """Restore cookies from backup into a fresh browser context.

    Playwright's ``context.add_cookies()`` requires at least one page to be
    open in the context (otherwise cookies may not persist to the profile's
    SQLite store).  We create a short-lived page on zhaopin.com, inject the
    cookies, verify they landed, then close the page.

    Returns True if backup was found and at/rt tokens were restored.
    """
    backup_path = profile_dir.resolve().parent / "zhilian_cookies_backup" / "zhilian_cookies.json"
    if not backup_path.exists():
        logger.info("[智联Browser] No cookie backup at %s", backup_path)
        return False
    try:
        cookies = json.loads(backup_path.read_text(encoding="utf-8"))
        if not cookies:
            return False
        # Need a page so add_cookies can write to the profile's cookie store
        page = await context.new_page()
        try:
            await page.goto("https://www.zhaopin.com/", wait_until="domcontentloaded")
            await context.add_cookies(cookies)
        finally:
            await page.close()
        # Verify at/rt are now present
        current = await context.cookies()
        names = {c["name"] for c in current}
        if "at" in names and "rt" in names:
            logger.info("[智联Browser] Cookies restored from backup (%d cookies)", len(cookies))
            return True
        logger.warning("[智联Browser] Cookie restore failed: at/rt not found after add_cookies")
        return False
    except Exception as e:
        logger.warning("[智联Browser] Failed to restore cookies: %s", e)
        return False


async def zhilian_browser_search(
    keyword: str,
    city_code: str = "0",
    profile_dir: str = "data/zhilian_browser_profile",
    headless: bool = False,
) -> list[dict]:
    """Convenience function: one-shot browser search.

    Uses the module-level singleton so that multiple calls within the same
    process reuse the same persistent Chromium context.
    """
    browser = await get_browser(profile_dir=profile_dir)
    return await browser.search(keyword=keyword, city_code=city_code, headless=headless)


async def zhilian_browser_login(
    profile_dir: str = "data/zhilian_browser_profile",
    timeout_s: int = 180,
) -> bool:
    """Convenience function: open browser for manual login.

    Uses the module-level singleton so login cookies persist for
    subsequent searches within the same process.
    """
    browser = await get_browser(profile_dir=profile_dir)
    return await browser.login(timeout_s=timeout_s)
