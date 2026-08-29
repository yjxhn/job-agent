"""Unit tests for pure helpers in playwright_jd.py (no real browser needed)."""

import json

from agent_core.platforms.playwright_jd import (
    PLATFORM_COOKIE_DOMAINS,
    PLATFORM_SELECTORS,
    _load_cookies_for_playwright,
    _slice_jd_from_body,
)


def test_platform_selectors_cover_all_live_adapters():
    for platform in (
        "boss_zhipin",
        "liepin",
        "zhilian",
        "byd",
        "naura",
        "netease",
        "tencent",
        "yofc",
    ):
        assert platform in PLATFORM_SELECTORS
        assert platform in PLATFORM_COOKIE_DOMAINS


def test_slice_jd_from_body_liepin():
    body = "头部\n职位介绍\n负责设备维护\n举报\n底部"
    assert "负责设备维护" in _slice_jd_from_body(body, "liepin")
    assert "举报" not in _slice_jd_from_body(body, "liepin")


def test_slice_jd_from_body_boss():
    body = "岗位职责：\n1. 安装调试\n2. 售后支持\n投诉建议\n尾部"
    jd = _slice_jd_from_body(body, "boss_zhipin")
    assert "1. 安装调试" in jd
    assert "投诉建议" not in jd


def test_slice_jd_from_body_no_marker_returns_empty():
    assert _slice_jd_from_body("没有任何标记", "boss_zhipin") == ""


def test_slice_jd_from_body_unknown_platform_returns_empty():
    assert _slice_jd_from_body("职位介绍\n内容", "not_a_platform") == ""


def test_load_cookies_missing_file_returns_empty(tmp_path):
    assert _load_cookies_for_playwright(str(tmp_path / "missing.json")) == []


def test_load_cookies_invalid_json_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert _load_cookies_for_playwright(str(p)) == []


def test_load_cookies_dict_with_cookies_key(tmp_path):
    p = tmp_path / "cookies.json"
    p.write_text(
        json.dumps(
            {"cookies": [{"name": "a", "value": "1", "domain": ".zhipin.com", "sameSite": "lax"}]}
        ),
        encoding="utf-8",
    )
    out = _load_cookies_for_playwright(str(p))
    assert len(out) == 1
    assert out[0]["sameSite"] == "Lax"


def test_load_cookies_normalizes_same_site(tmp_path):
    p = tmp_path / "cookies.json"
    p.write_text(
        json.dumps(
            [
                {"name": "a", "value": "1", "domain": "x", "sameSite": "weird"},
                {"name": "b", "value": "2", "domain": "x", "sameSite": "None"},
            ]
        ),
        encoding="utf-8",
    )
    out = _load_cookies_for_playwright(str(p))
    assert out[0]["sameSite"] == "Lax"
    assert out[1]["sameSite"] == "None"


def test_idle_expired_false_when_no_deadline(monkeypatch):
    from agent_core.platforms import playwright_jd as pjd
    from agent_core.platforms.browser_manager import BrowserManager

    monkeypatch.setattr(pjd, "_idle_manager", BrowserManager())
    assert pjd._idle_expired() is False


def test_cancel_idle_timer_none_is_noop():
    from agent_core.platforms import playwright_jd as pjd

    old = pjd._idle_task
    pjd._idle_task = None
    try:
        pjd._cancel_idle_timer()
    finally:
        pjd._idle_task = old


def test_schedule_idle_close_without_loop_sets_deadline(monkeypatch):
    from agent_core.platforms import playwright_jd as pjd
    from agent_core.platforms.browser_manager import BrowserManager

    monkeypatch.setattr(pjd, "_idle_manager", BrowserManager())
    monkeypatch.setattr(pjd, "_idle_task", None)
    pjd._schedule_idle_close()
    assert pjd._idle_manager._idle_deadline is not None
    assert pjd._idle_expired() is False
