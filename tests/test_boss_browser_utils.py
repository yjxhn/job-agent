"""Unit tests for pure helpers in boss_browser.py (no real browser needed)."""

import asyncio

from agent_core.platforms.boss_browser import BossBrowser, _slice_jd_from_body


def test_slice_jd_from_body_boss():
    body = "岗位职责\n1. 设备维护\n2. 故障诊断\n举报\n底部"
    jd = _slice_jd_from_body(body)
    assert "1. 设备维护" in jd
    assert "举报" not in jd


def test_slice_jd_from_body_no_marker_returns_empty():
    assert _slice_jd_from_body("这里没有任何 JD 标记") == ""


def test_slice_jd_from_body_trailing_marker_stops():
    body = "职位描述：\n负责 AMR 调试\n看了该职位的人还看了\n推荐"
    jd = _slice_jd_from_body(body)
    assert "负责 AMR 调试" in jd
    assert "看了该职位的人还看了" not in jd


def test_fetch_jd_invalid_url_returns_empty_without_browser():
    browser = BossBrowser(profile_dir="unused")
    # No browser/playwright installed path should ever be reached for invalid URL.
    assert asyncio.run(browser.fetch_jd("")) == ""
    assert asyncio.run(browser.fetch_jd("ftp://example.com")) == ""
