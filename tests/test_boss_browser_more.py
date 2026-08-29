"""Additional focused unit tests for agent_core.platforms.boss_browser.

All browser objects are fakes; no real Chromium, network, or Playwright
automation is used.
"""

import asyncio
import atexit
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_core.platforms import boss_browser as bb
from agent_core.platforms.boss_browser import (
    BossBrowser,
    _slice_jd_from_body,
    close_browser,
    fetch_jd,
    get_browser,
    login,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Prevent any accidental real asyncio.sleep in browser-flow tests."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


# ── Fakes ────────────────────────────────────────────────────────────────


class _FakeElement:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _FakePage:
    def __init__(
        self,
        url="https://www.zhipin.com/job_detail/123.html",
        selector_texts=None,
        body_text="",
        goto_errors=None,
    ):
        self.url = url
        self.selector_texts = selector_texts or {}
        self.body_text = body_text
        self.goto_errors = list(goto_errors or [])
        self.closed = False
        self.goto_url = None
        self.load_state_called = False

    async def goto(self, url, **kwargs):
        self.goto_url = url
        if self.goto_errors:
            error = self.goto_errors.pop(0)
            if error is not None:
                raise error
        self.url = url

    async def wait_for_load_state(self, state, timeout=None):
        self.load_state_called = True

    async def query_selector(self, selector):
        if selector in self.selector_texts:
            return _FakeElement(self.selector_texts[selector])
        return None

    async def inner_text(self, selector="body"):
        if selector == "body":
            return self.body_text
        return self.selector_texts.get(selector, "")

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, page=None, cookies=None, browser=None):
        self._page = page or _FakePage()
        self._cookies = cookies or []
        self.browser = browser or SimpleNamespace(is_connected=lambda: True)
        self.closed = False
        self.init_scripts = []
        self.new_page = AsyncMock(return_value=self._page)

    async def add_init_script(self, script):
        self.init_scripts.append(script)

    async def cookies(self):
        return self._cookies

    async def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self, context):
        self._context = context
        self.launch_kwargs = None
        self.stopped = False

    @property
    def chromium(self):
        return self

    async def launch_persistent_context(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._context

    async def start(self):
        return self

    async def stop(self):
        self.stopped = True


class _AsyncPlaywrightStarter:
    def __init__(self, playwright):
        self._playwright = playwright

    async def start(self):
        return self._playwright


class _FakeManager:
    def __init__(self):
        self.browser = None
        self.closed = False

    def set_browser(self, browser):
        self.browser = browser

    def clear_browser(self):
        self.browser = None

    async def close_browser(self):
        self.closed = True
        self.browser = None


# ── _slice_jd_from_body extra branches ───────────────────────────────────


def test_slice_jd_from_body_strips_heading_and_colon():
    body = "任职要求：\n熟悉 Python\n举报"
    jd = _slice_jd_from_body(body)
    assert jd == "熟悉 Python"
    assert "举报" not in jd


def test_slice_jd_from_body_uses_earliest_trailing_marker():
    body = "岗位职责\n开发\n投诉\n相似职位\n尾部"
    jd = _slice_jd_from_body(body)
    assert jd == "开发"
    assert "投诉" not in jd


def test_slice_jd_from_body_empty_when_no_heading():
    assert _slice_jd_from_body("只有底部内容") == ""


def test_slice_jd_from_body_multiline_keeps_interior_text():
    body = "职位描述：\n第一行\n第二行\nAPP下载\n第三行"
    jd = _slice_jd_from_body(body)
    assert "第一行" in jd
    assert "第二行" in jd
    assert "APP下载" not in jd


# ── BossBrowser init / browser lifecycle ─────────────────────────────────


def test_browser_init_creates_profile_dir(tmp_path):
    profile = tmp_path / "boss_profile"
    browser = BossBrowser(profile_dir=profile)
    assert browser._profile_dir == profile
    assert profile.exists()


async def test_ensure_browser_launches_persistent_context(monkeypatch, tmp_path):
    context = _FakeContext()
    playwright = _FakePlaywright(context)
    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: _AsyncPlaywrightStarter(playwright),
    )
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    await browser._ensure_browser(headless=True)
    assert browser._context is context
    assert browser._playwright is playwright
    assert playwright.launch_kwargs["headless"] is True
    assert playwright.launch_kwargs["user_data_dir"] == str(tmp_path / "profile")
    assert context.init_scripts == [bb._ANTI_DETECTION_SCRIPT]


async def test_ensure_browser_reuses_live_context(tmp_path):
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    context = _FakeContext()
    browser._context = context
    await browser._ensure_browser()
    assert browser._context is context


async def test_ensure_browser_relaunches_dead_context(monkeypatch, tmp_path):
    dead_context = _FakeContext(browser=SimpleNamespace(is_connected=lambda: False))
    new_context = _FakeContext()
    playwright = _FakePlaywright(new_context)
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = dead_context
    removed = []

    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: _AsyncPlaywrightStarter(playwright),
    )
    monkeypatch.setattr(
        "agent_core.platforms.browser_utils.remove_stale_lock_files",
        lambda path: removed.append(path),
    )
    await browser._ensure_browser()
    assert dead_context.closed is True
    assert browser._context is new_context
    assert removed


async def test_ensure_browser_missing_playwright_raises(monkeypatch, tmp_path):
    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    with pytest.raises(RuntimeError, match="playwright not installed"):
        await browser._ensure_browser()


async def test_teardown_context_closes_and_removes_locks(monkeypatch, tmp_path):
    context = _FakeContext()
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    removed = []
    monkeypatch.setattr(
        "agent_core.platforms.browser_utils.remove_stale_lock_files",
        lambda path: removed.append(path),
    )
    await browser._teardown_context()
    assert context.closed is True
    assert browser._context is None
    assert removed == [tmp_path / "profile"]


async def test_teardown_context_ignores_close_error(monkeypatch, tmp_path):
    class _BrokenContext(_FakeContext):
        async def close(self):
            raise RuntimeError("close failed")

    context = _BrokenContext()
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    monkeypatch.setattr(
        "agent_core.platforms.browser_utils.remove_stale_lock_files",
        lambda path: None,
    )
    await browser._teardown_context()
    assert browser._context is None


# ── login() ──────────────────────────────────────────────────────────────


async def test_login_success_returns_true(monkeypatch, tmp_path):
    context = _FakeContext(cookies=[{"name": "wt2"}, {"name": "wbg"}])
    page = _FakePage()
    context.new_page = AsyncMock(return_value=page)
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    assert await browser.login(timeout_s=10) is True
    assert page.closed is True


async def test_login_timeout_returns_false(monkeypatch, tmp_path):
    class _FakeLoop:
        def __init__(self):
            self.current = 0.0

        def time(self):
            self.current += 10
            return self.current

    context = _FakeContext(cookies=[])
    page = _FakePage()
    context.new_page = AsyncMock(return_value=page)
    fake_loop = _FakeLoop()
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())
    monkeypatch.setattr(asyncio, "get_event_loop", lambda: fake_loop)

    assert await browser.login(timeout_s=5) is False
    assert page.closed is True


# ── fetch_jd() ───────────────────────────────────────────────────────────


async def _browser_with_page(page, tmp_path):
    context = _FakeContext(page=page)
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    return browser, context


async def test_fetch_jd_selector_success(monkeypatch, tmp_path):
    page = _FakePage(selector_texts={".job-detail .job-sec-text": "岗位职责\n" + "A" * 80})
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert result.startswith("岗位职责")
    assert len(result) > 20
    assert page.closed is True


async def test_fetch_jd_redirects_to_security_returns_empty(monkeypatch, tmp_path):
    security_url = "https://www.zhipin.com/passport/zp/security?x=1"
    page = _FakePage(url=security_url)
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    result = await browser.fetch_jd(security_url)
    assert result == ""
    assert page.closed is True


async def test_fetch_jd_launch_failure_retries_once(monkeypatch, tmp_path):
    page = _FakePage(selector_texts={".job-sec-text": "B" * 60})
    browser, context = await _browser_with_page(page, tmp_path)
    ensure = AsyncMock(side_effect=[RuntimeError("Failed to launch"), None])
    monkeypatch.setattr(browser, "_ensure_browser", ensure)
    monkeypatch.setattr(browser, "_teardown_context", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert result == "B" * 60
    assert ensure.await_count == 2


async def test_fetch_jd_launch_failure_non_retryable_returns_empty(monkeypatch, tmp_path):
    browser, _ = await _browser_with_page(_FakePage(), tmp_path)
    monkeypatch.setattr(
        browser,
        "_ensure_browser",
        AsyncMock(side_effect=ValueError("boom")),
    )
    assert await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html") == ""


async def test_fetch_jd_new_page_failure_retries_once(monkeypatch, tmp_path):
    page = _FakePage(selector_texts={".text": "C" * 60})
    context = _FakeContext(page=page)
    context.new_page = AsyncMock(
        side_effect=[
            RuntimeError("Target page, context or browser has been closed"),
            page,
        ]
    )
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())
    monkeypatch.setattr(browser, "_teardown_context", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert result == "C" * 60
    assert context.new_page.await_count == 2


async def test_fetch_jd_new_page_non_retryable_returns_empty(monkeypatch, tmp_path):
    context = _FakeContext()
    context.new_page = AsyncMock(side_effect=ValueError("boom"))
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())
    assert await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html") == ""


async def test_fetch_jd_nav_error_retries_once(monkeypatch, tmp_path):
    page = _FakePage(
        selector_texts={".job-sec-text": "D" * 60},
        goto_errors=[
            RuntimeError("Target page, context or browser has been closed"),
            None,
        ],
    )
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())
    monkeypatch.setattr(browser, "_teardown_context", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert result == "D" * 60
    assert page.goto_url == "https://www.zhipin.com/job_detail/1.html"


async def test_fetch_jd_generic_error_returns_empty(monkeypatch, tmp_path):
    page = _FakePage(goto_errors=[ValueError("bad page")])
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())
    assert await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html") == ""


async def test_fetch_jd_fallback_body_slice(monkeypatch, tmp_path):
    page = _FakePage(body_text="岗位职责\n负责机器人调试\n举报\n底部")
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert "负责机器人调试" in result
    assert "举报" not in result


async def test_fetch_jd_fallback_long_body_without_marker(monkeypatch, tmp_path):
    page = _FakePage(body_text="X" * 150)
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert result == "X" * 150


async def test_fetch_jd_fallback_short_body_without_marker_returns_empty(monkeypatch, tmp_path):
    page = _FakePage(body_text="太短")
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    assert await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html") == ""


async def test_fetch_jd_truncates_to_5000(monkeypatch, tmp_path):
    page = _FakePage(selector_texts={".text": "E" * 6000})
    browser, _ = await _browser_with_page(page, tmp_path)
    monkeypatch.setattr(browser, "_ensure_browser", AsyncMock())

    result = await browser.fetch_jd("https://www.zhipin.com/job_detail/1.html")
    assert len(result) == 5000
    assert result == "E" * 5000


# ── close() ──────────────────────────────────────────────────────────────


async def test_close_stops_playwright(tmp_path):
    context = _FakeContext()
    playwright = _FakePlaywright(context)
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    browser._playwright = playwright

    await browser.close()
    assert context.closed is True
    assert playwright.stopped is True
    assert browser._playwright is None


async def test_close_ignores_stop_error(tmp_path):
    class _BrokenPlaywright(_FakePlaywright):
        async def stop(self):
            raise RuntimeError("stop failed")

    context = _FakeContext()
    playwright = _BrokenPlaywright(context)
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser._context = context
    browser._playwright = playwright

    await browser.close()
    assert browser._playwright is None


# ── Module-level singleton helpers ───────────────────────────────────────


async def test_get_browser_creates_and_ensures_singleton(monkeypatch, tmp_path):
    class _FakeBossBrowser:
        def __init__(self, profile_dir):
            self.profile_dir = profile_dir
            self.ensured = False

        async def _ensure_browser(self, headless=False):
            self.ensured = True

    manager = _FakeManager()
    monkeypatch.setattr(bb, "_manager", manager)
    monkeypatch.setattr(bb, "_browser_lock", asyncio.Lock())
    monkeypatch.setattr(bb, "_cleanup_registered", False)
    monkeypatch.setattr(bb, "_register_cleanup", lambda: None)
    monkeypatch.setattr(bb, "BossBrowser", _FakeBossBrowser)

    browser = await get_browser(profile_dir=tmp_path / "profile")
    assert manager.browser is browser
    assert browser.ensured is True
    assert bb._cleanup_registered is True


async def test_get_browser_retries_once_on_launch_failure(monkeypatch, tmp_path):
    class _RetryBrowser:
        def __init__(self, profile_dir):
            self.profile_dir = profile_dir
            self.ensure_calls = 0
            self.teardown_calls = 0

        async def _ensure_browser(self, headless=False):
            self.ensure_calls += 1
            if self.ensure_calls == 1:
                raise RuntimeError("SingletonLock")

        async def _teardown_context(self):
            self.teardown_calls += 1

    manager = _FakeManager()
    monkeypatch.setattr(bb, "_manager", manager)
    monkeypatch.setattr(bb, "_browser_lock", asyncio.Lock())
    monkeypatch.setattr(bb, "_cleanup_registered", False)
    monkeypatch.setattr(bb, "_register_cleanup", lambda: None)
    monkeypatch.setattr(bb, "BossBrowser", _RetryBrowser)

    browser = await get_browser(profile_dir=tmp_path / "profile")
    assert browser.ensure_calls == 2
    assert browser.teardown_calls == 1


async def test_close_browser_delegates_to_manager(monkeypatch):
    manager = _FakeManager()
    monkeypatch.setattr(bb, "_manager", manager)
    monkeypatch.setattr(bb, "_browser_lock", asyncio.Lock())
    await close_browser()
    assert manager.closed is True


async def test_module_fetch_jd_uses_singleton(monkeypatch, tmp_path):
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser.fetch_jd = AsyncMock(return_value="JD TEXT")

    async def _fake_get_browser(*args, **kwargs):
        return browser

    monkeypatch.setattr(bb, "get_browser", _fake_get_browser)
    assert await fetch_jd("https://www.zhipin.com/job_detail/1.html") == "JD TEXT"
    browser.fetch_jd.assert_awaited_once_with(
        "https://www.zhipin.com/job_detail/1.html", headless=False
    )


async def test_module_login_uses_singleton(monkeypatch, tmp_path):
    browser = BossBrowser(profile_dir=tmp_path / "profile")
    browser.login = AsyncMock(return_value=True)

    async def _fake_get_browser(*args, **kwargs):
        return browser

    monkeypatch.setattr(bb, "get_browser", _fake_get_browser)
    assert await login(timeout_s=99) is True
    browser.login.assert_awaited_once_with(timeout_s=99)


def test_register_cleanup_does_not_raise(monkeypatch):
    registered = []
    monkeypatch.setattr(atexit, "register", lambda func: registered.append(func))
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    bb._register_cleanup()
    assert registered
