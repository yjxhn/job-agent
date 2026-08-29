"""Tests for the unified BrowserManager lifecycle helper."""

import asyncio

from agent_core.platforms.browser_manager import BrowserManager


def test_touch_and_idle_expired(monkeypatch):
    import time as time_mod

    mgr = BrowserManager(idle_close_seconds=60)
    now = [100.0]
    monkeypatch.setattr(time_mod, "monotonic", lambda: now[0])
    mgr.set_browser(object())
    assert mgr.idle_expired() is False
    now[0] += 61
    assert mgr.idle_expired() is True


def test_clear_browser_resets_deadline():
    mgr = BrowserManager()
    mgr.set_browser(object())
    mgr.clear_browser()
    assert mgr.browser is None
    assert mgr.idle_expired() is False


def test_close_browser_none_is_noop():
    mgr = BrowserManager()
    asyncio.run(mgr.close_browser())


def test_close_browser_async_close(monkeypatch):
    closed = []

    class _FakeBrowser:
        async def close(self):
            closed.append(1)

    mgr = BrowserManager()
    mgr.set_browser(_FakeBrowser())
    asyncio.run(mgr.close_browser())
    assert closed == [1]
    assert mgr.browser is None
