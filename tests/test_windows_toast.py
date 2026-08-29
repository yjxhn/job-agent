"""Tests for Windows Toast helpers (no real toast triggered)."""

from unittest.mock import MagicMock

from agent_core.notify import windows_toast as wt


def test_notify_search_complete_message(monkeypatch):
    calls = []

    def fake_notify(title, msg):
        calls.append((title, msg))

    monkeypatch.setattr(wt, "notify", fake_notify)
    wt.notify_search_complete(3)
    assert calls == [("搜索完成", "找到 3 个新岗位")]


def test_notify_search_complete_with_skipped(monkeypatch):
    calls = []

    def fake_notify(title, msg):
        calls.append((title, msg))

    monkeypatch.setattr(wt, "notify", fake_notify)
    wt.notify_search_complete(0, skipped=2)
    assert "2 个" in calls[0][1]


def test_notify_helpers_route_to_notify(monkeypatch):
    calls = []

    def fake_notify(title, msg):
        calls.append((title, msg))

    monkeypatch.setattr(wt, "notify", fake_notify)
    wt.notify_captcha("Boss")
    wt.notify_cookie_expired("猎聘")
    wt.notify_anti_bot("智联")
    wt.notify_application_reminder(4)
    assert len(calls) == 4
    assert calls[0][0] == "需要验证"
    assert calls[-1][0] == "投递跟进提醒"


def test_notify_powershell_fallback(monkeypatch):
    """When winotify is missing, PowerShell fallback runs and failures are swallowed."""
    import sys

    monkeypatch.setitem(sys.modules, "winotify", None)
    run = MagicMock()
    monkeypatch.setattr(wt.subprocess, "run", run)
    wt.notify("标题", "内容")
    assert run.call_count == 1
