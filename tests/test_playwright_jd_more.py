"""Additional unit tests for playwright_jd non-browser and mocked-browser paths.

These tests deliberately avoid real network/browser launches.  The browser
factory is faked with ``sys.modules`` entries, and page/context objects are
``AsyncMock`` instances so every fetch branch can be exercised deterministically.
"""

import asyncio
import builtins
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_core.platforms import playwright_jd as pjd
from agent_core.platforms.browser_manager import BrowserManager

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _install_fake_playwright(monkeypatch, async_playwright):
    """Make ``from playwright.async_api import async_playwright`` resolve to fake."""
    fake_pw = types.ModuleType("playwright")
    fake_api = types.ModuleType("playwright.async_api")
    fake_api.async_playwright = async_playwright
    monkeypatch.setitem(sys.modules, "playwright", fake_pw)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_api)


def _fake_playwright(browser=None, context=None):
    browser = browser if browser is not None else AsyncMock()
    context = context if context is not None else AsyncMock()
    context.add_init_script = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    pw = SimpleNamespace()
    pw.chromium = SimpleNamespace(launch=AsyncMock(return_value=browser))

    async def _start():
        return pw

    pw.start = _start
    return pw, browser, context


class _FakePage:
    """Minimal async page double used by fetch_jd_playwright tests."""

    def __init__(self):
        self.goto = AsyncMock()
        self.wait_for_load_state = AsyncMock()
        self.query_selector = AsyncMock(return_value=None)
        self.inner_text = AsyncMock(return_value="")
        self.close = AsyncMock()


def _fake_fetch_env(monkeypatch, page=None, context=None, cookies=None):
    page = page if page is not None else _FakePage()
    context = context if context is not None else AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    inst = {"context": context}
    monkeypatch.setattr(pjd, "_ensure_browser", AsyncMock(return_value=inst))
    monkeypatch.setattr(pjd, "_load_cookies_for_playwright", lambda path: cookies or [])
    monkeypatch.setattr(pjd, "_schedule_idle_close", lambda: None)
    monkeypatch.setattr(pjd, "_idle_expired", lambda: False)
    monkeypatch.setattr(pjd, "_browser_instance", None)
    monkeypatch.setattr(pjd, "_idle_manager", BrowserManager())
    return inst


def _el_with_text(text):
    el = AsyncMock()
    el.inner_text = AsyncMock(return_value=text)
    return el


# ---------------------------------------------------------------------------
# idle timer / browser lifecycle helpers
# ---------------------------------------------------------------------------


def test_cancel_idle_timer_cancels_active_task(monkeypatch):
    task = MagicMock()
    monkeypatch.setattr(pjd, "_idle_task", task)
    pjd._cancel_idle_timer()
    task.cancel.assert_called_once()
    assert pjd._idle_task is None


@pytest.mark.asyncio
async def test_schedule_idle_close_with_running_loop_closes_after_idle(monkeypatch):
    monkeypatch.setattr(pjd, "_idle_manager", BrowserManager())
    monkeypatch.setattr(pjd, "_idle_task", None)
    monkeypatch.setattr(pjd, "_browser_instance", {"browser": object()})

    closed = []

    async def fake_close():
        closed.append(1)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(pjd, "close_browser", fake_close)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    pjd._schedule_idle_close()
    assert pjd._idle_task is not None
    await pjd._idle_task
    assert closed == [1]


def test_slice_jd_from_body_liepin_secondary_marker(monkeypatch):
    # "岗位职责" is the second marker for liepin; this exercises the branch where
    # the marker loop first sees a non-matching marker before trimming.
    body = "页面头部\n岗位职责\n负责设备维护\n举报\n页脚"
    jd = pjd._slice_jd_from_body(body, "liepin")
    assert "负责设备维护" in jd
    assert "举报" not in jd


def test_close_browser_closes_instance(monkeypatch):
    context = AsyncMock()
    browser = AsyncMock()
    pw = AsyncMock()
    monkeypatch.setattr(
        pjd,
        "_browser_instance",
        {"context": context, "browser": browser, "playwright": pw},
    )

    asyncio.run(pjd.close_browser())

    context.close.assert_awaited_once()
    browser.close.assert_awaited_once()
    pw.stop.assert_awaited_once()
    assert pjd._browser_instance is None


def test_close_browser_no_instance(monkeypatch):
    monkeypatch.setattr(pjd, "_browser_instance", None)
    asyncio.run(pjd.close_browser())  # must not raise


def test_close_browser_swallows_close_errors(monkeypatch):
    context = AsyncMock()
    context.close.side_effect = RuntimeError("ctx")
    browser = AsyncMock()
    browser.close.side_effect = RuntimeError("browser")
    pw = AsyncMock()
    pw.stop.side_effect = RuntimeError("stop")
    monkeypatch.setattr(
        pjd,
        "_browser_instance",
        {"context": context, "browser": browser, "playwright": pw},
    )

    asyncio.run(pjd.close_browser())

    assert pjd._browser_instance is None


# ---------------------------------------------------------------------------
# _ensure_browser
# ---------------------------------------------------------------------------


def test_ensure_browser_launches_new_instance(monkeypatch):
    registered = []
    monkeypatch.setattr("atexit.register", lambda fn: registered.append(fn))
    monkeypatch.setattr(pjd, "_browser_instance", None)
    monkeypatch.setattr(pjd, "_cleanup_registered", False)

    pw, browser, context = _fake_playwright()
    _install_fake_playwright(monkeypatch, lambda: pw)

    inst = asyncio.run(pjd._ensure_browser(headless=True))

    assert inst["browser"] is browser
    assert inst["context"] is context
    assert inst["playwright"] is pw
    pw.chromium.launch.assert_awaited_once()
    assert pw.chromium.launch.await_args.kwargs["headless"] is True
    context.add_init_script.assert_awaited_once()
    assert len(registered) == 1
    assert pjd._cleanup_registered is True


def test_ensure_browser_reuses_live_instance(monkeypatch):
    browser = MagicMock()
    browser.is_connected.return_value = True
    context = MagicMock()
    context.pages = []
    inst = {"browser": browser, "context": context}
    monkeypatch.setattr(pjd, "_browser_instance", inst)

    result = asyncio.run(pjd._ensure_browser())

    assert result is inst


def test_ensure_browser_relaunches_dead_instance(monkeypatch):
    old_context = AsyncMock()
    old_browser = MagicMock()
    old_browser.is_connected.return_value = False
    old_browser.close = AsyncMock()
    old_inst = {"browser": old_browser, "context": old_context, "playwright": AsyncMock()}
    monkeypatch.setattr(pjd, "_browser_instance", old_inst)
    monkeypatch.setattr(pjd, "_cleanup_registered", True)

    pw, browser, context = _fake_playwright()
    _install_fake_playwright(monkeypatch, lambda: pw)

    inst = asyncio.run(pjd._ensure_browser())

    assert inst is not old_inst
    old_context.close.assert_awaited_once()
    old_browser.close.assert_awaited_once()
    assert inst["browser"] is browser


def test_ensure_browser_relaunches_when_liveness_check_raises(monkeypatch):
    old_context = AsyncMock()
    old_browser = MagicMock()
    old_browser.is_connected.side_effect = RuntimeError("boom")
    old_browser.close = AsyncMock()
    old_inst = {"browser": old_browser, "context": old_context, "playwright": AsyncMock()}
    monkeypatch.setattr(pjd, "_browser_instance", old_inst)
    monkeypatch.setattr(pjd, "_cleanup_registered", True)

    pw, browser, context = _fake_playwright()
    _install_fake_playwright(monkeypatch, lambda: pw)

    inst = asyncio.run(pjd._ensure_browser())

    assert inst["browser"] is browser
    old_context.close.assert_awaited_once()
    old_browser.close.assert_awaited_once()


def test_ensure_browser_skips_atexit_when_already_registered(monkeypatch):
    monkeypatch.setattr(pjd, "_browser_instance", None)
    monkeypatch.setattr(pjd, "_cleanup_registered", True)
    monkeypatch.setattr("atexit.register", lambda fn: pytest.fail("should not register"))

    pw, browser, context = _fake_playwright()
    _install_fake_playwright(monkeypatch, lambda: pw)

    inst = asyncio.run(pjd._ensure_browser())

    assert inst["browser"] is browser
    assert pjd._cleanup_registered is True


def test_ensure_browser_missing_playwright_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(pjd, "_browser_instance", None)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("missing playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="playwright not installed"):
        asyncio.run(pjd._ensure_browser())


# ---------------------------------------------------------------------------
# fetch_jd_playwright
# ---------------------------------------------------------------------------


def test_fetch_invalid_url_returns_empty(monkeypatch):
    monkeypatch.setattr(pjd, "_ensure_browser", AsyncMock())
    assert asyncio.run(pjd.fetch_jd_playwright("not-http", "boss_zhipin", "c.json")) == ""
    pjd._ensure_browser.assert_not_called()


def test_fetch_unknown_platform_returns_empty(monkeypatch):
    monkeypatch.setattr(pjd, "_ensure_browser", AsyncMock())
    assert asyncio.run(pjd.fetch_jd_playwright("https://x", "unknown", "c.json")) == ""
    pjd._ensure_browser.assert_not_called()


def test_fetch_closes_stale_browser_before_reuse(monkeypatch):
    page = _FakePage()
    close_browser = AsyncMock()
    _fake_fetch_env(monkeypatch, page=page, cookies=[])
    monkeypatch.setattr(pjd, "_browser_instance", {"stale": True})
    monkeypatch.setattr(pjd, "_idle_expired", lambda: True)
    monkeypatch.setattr(pjd, "close_browser", close_browser)

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert result == ""
    close_browser.assert_awaited_once()


def test_fetch_browser_init_error_returns_empty(monkeypatch):
    page = _FakePage()
    _fake_fetch_env(monkeypatch, page=page, cookies=[])
    monkeypatch.setattr(pjd, "_ensure_browser", AsyncMock(side_effect=RuntimeError("init")))

    assert asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json")) == ""


def test_fetch_filters_cookies_by_platform(monkeypatch):
    page = _FakePage()
    context = AsyncMock()
    cookies = [
        {"domain": ".zhipin.com", "name": "ok"},
        {"domain": "evil.example", "name": "bad"},
    ]
    _fake_fetch_env(monkeypatch, page=page, context=context, cookies=cookies)

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert result == ""
    context.add_cookies.assert_awaited_once_with([cookies[0]])


def test_fetch_does_not_add_cookies_when_filtered_empty(monkeypatch):
    page = _FakePage()
    context = AsyncMock()
    _fake_fetch_env(
        monkeypatch,
        page=page,
        context=context,
        cookies=[{"domain": "evil.example", "name": "bad"}],
    )

    asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    context.add_cookies.assert_not_awaited()


def test_fetch_add_cookies_error_is_swallowed(monkeypatch):
    page = _FakePage()
    context = AsyncMock()
    context.add_cookies = AsyncMock(side_effect=RuntimeError("cookies"))
    _fake_fetch_env(
        monkeypatch,
        page=page,
        context=context,
        cookies=[{"domain": ".zhipin.com", "name": "ok"}],
    )

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert result == ""


def test_fetch_goto_error_returns_empty(monkeypatch):
    page = _FakePage()
    page.goto = AsyncMock(side_effect=RuntimeError("goto"))
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert result == ""
    page.close.assert_awaited_once()


def test_fetch_selector_match_returns_jd(monkeypatch):
    page = _FakePage()
    el = _el_with_text("  JD text that is definitely longer than twenty characters.  ")
    page.query_selector.return_value = el
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert result == "JD text that is definitely longer than twenty characters."
    page.query_selector.assert_awaited_once()
    page.close.assert_awaited_once()


def test_fetch_networkidle_timeout_is_ignored(monkeypatch):
    page = _FakePage()
    page.wait_for_load_state = AsyncMock(side_effect=RuntimeError("networkidle"))
    el = _el_with_text("A real JD description that is long enough to be accepted.")
    page.query_selector.return_value = el
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert "long enough" in result


def test_fetch_selector_exception_continues_to_next_selector(monkeypatch):
    page = _FakePage()
    el = _el_with_text("Fallback selector JD text that is long enough to pass.")
    page.query_selector.side_effect = [RuntimeError("first"), el]
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert "Fallback selector" in result


def test_fetch_short_selector_falls_back_to_body_text(monkeypatch):
    page = _FakePage()
    short_el = _el_with_text("short")
    page.query_selector.return_value = short_el
    body = "x" * 120
    page.inner_text.return_value = body
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "tencent", "c.json"))

    assert result == body


def test_fetch_body_text_slices_jd_region(monkeypatch):
    page = _FakePage()
    body = "顶部导航\n职位介绍\n负责设备维护\n举报\n底部"
    page.inner_text.return_value = body
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "liepin", "c.json"))

    assert "负责设备维护" in result
    assert "举报" not in result


def test_fetch_empty_body_returns_empty(monkeypatch):
    page = _FakePage()
    page.inner_text.return_value = ""
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    assert asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json")) == ""


def test_fetch_truncates_long_jd(monkeypatch):
    page = _FakePage()
    el = _el_with_text("A" * 6000)
    page.query_selector.return_value = el
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert len(result) == 5000


def test_fetch_page_close_error_is_swallowed(monkeypatch):
    page = _FakePage()
    page.close = AsyncMock(side_effect=RuntimeError("close"))
    el = _el_with_text("A real JD description that is long enough to be accepted.")
    page.query_selector.return_value = el
    _fake_fetch_env(monkeypatch, page=page, cookies=[])

    result = asyncio.run(pjd.fetch_jd_playwright("https://x", "boss_zhipin", "c.json"))

    assert "long enough" in result
