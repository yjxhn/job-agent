"""Playwright-path tests with mocked browser layer (T5-3).

Covers the pure/extractable logic that previously had zero coverage:
- playwright_jd._slice_jd_from_body (body-text JD recovery)
- platform selector / cookie-domain / heading-marker registry completeness
- zhilian_browser cookie backup/restore round-trip (mock context)
"""

import json
from unittest.mock import AsyncMock

from agent_core.platforms import playwright_jd, zhilian_browser
from agent_core.platforms.playwright_jd import _slice_jd_from_body

PLATFORMS = [
    "boss_zhipin",
    "liepin",
    "zhilian",
    "byd",
    "naura",
    "netease",
    "tencent",
    "yofc",
]


def test_platform_selectors_cover_all_platforms():
    assert set(playwright_jd.PLATFORM_SELECTORS.keys()) >= set(PLATFORMS)
    for p in PLATFORMS:
        assert playwright_jd.PLATFORM_SELECTORS[p], f"{p} has no selectors"


def test_platform_cookie_domains_cover_all_platforms():
    assert set(playwright_jd.PLATFORM_COOKIE_DOMAINS.keys()) >= set(PLATFORMS)
    for p in PLATFORMS:
        assert playwright_jd.PLATFORM_COOKIE_DOMAINS[p], f"{p} has no cookie domains"


def test_heading_markers_cover_slice_supported_platforms():
    # The body-text slicer is deliberately wired for the three job-board
    # platforms only; enterprise pages (tencent/netease/byd/naura/yofc)
    # rely on CSS selectors instead.
    assert set(playwright_jd._JD_HEADING_MARKERS.keys()) == {
        "liepin",
        "boss_zhipin",
        "zhilian",
    }


# ------------------------------------------------------------ slicing --------


def test_slice_finds_heading_and_trims_trailing_chrome():
    body = (
        "页面头部导航栏内容\n"
        "岗位职责：\n负责设备的安装调试\n任职要求：\n3年以上经验\n"
        "猜你喜欢\n推荐职位一"
    )
    jd = _slice_jd_from_body(body, "boss_zhipin")
    assert "负责设备的安装调试" in jd
    assert "猜你喜欢" not in jd
    assert "页面头部" not in jd


def test_slice_returns_empty_without_heading():
    assert _slice_jd_from_body("没有任何标记的正文", "boss_zhipin") == ""


def test_slice_handles_colon_variants():
    body = "职位描述: 负责 AMR 调度\n举报\n页脚"
    jd = _slice_jd_from_body(body, "liepin")
    assert "负责 AMR 调度" in jd
    assert "举报" not in jd


def test_slice_unknown_platform_returns_empty():
    assert _slice_jd_from_body("岗位职责：x", "unknown_platform") == ""


# ---------------------------------------------------- cookie backup ---------


def test_backup_and_restore_cookies_roundtrip(tmp_path, monkeypatch):
    """Backup writes a JSON file; restore re-injects and verifies at/rt."""
    monkeypatch.chdir(tmp_path)  # _backup_cookies uses CWD-relative path
    profile_dir = tmp_path / "data" / "zhilian_browser_profile"
    profile_dir.mkdir(parents=True)

    cookies = [
        {"name": "at", "value": "tok_at", "domain": ".zhaopin.com"},
        {"name": "rt", "value": "tok_rt", "domain": ".zhaopin.com"},
    ]
    import asyncio

    asyncio.run(zhilian_browser._backup_cookies(cookies, profile_dir))
    backup_file = tmp_path / "data" / "zhilian_cookies_backup" / "zhilian_cookies.json"
    assert backup_file.exists()
    assert json.loads(backup_file.read_text(encoding="utf-8")) == cookies

    # Mock context: new_page/goto/add_cookies/cookies(at+rt present)
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=AsyncMock())
    page = context.new_page.return_value
    page.goto = AsyncMock()
    page.close = AsyncMock()
    context.add_cookies = AsyncMock()
    context.cookies = AsyncMock(return_value=[{"name": "at"}, {"name": "rt"}])

    restored = asyncio.run(zhilian_browser._restore_cookies(context, profile_dir))
    assert restored is True
    context.add_cookies.assert_awaited_once_with(cookies)


def test_restore_cookies_missing_backup_returns_false(tmp_path):
    import asyncio

    context = AsyncMock()
    restored = asyncio.run(zhilian_browser._restore_cookies(context, tmp_path / "nope_profile"))
    assert restored is False
    context.new_page.assert_not_called()


def test_restore_cookies_verifies_at_rt(tmp_path, monkeypatch):
    """If at/rt are not present after injection, restore reports failure."""
    monkeypatch.chdir(tmp_path)
    profile_dir = tmp_path / "data" / "zhilian_browser_profile"
    profile_dir.mkdir(parents=True)
    backup_dir = tmp_path / "data" / "zhilian_cookies_backup"
    backup_dir.mkdir(parents=True)
    (backup_dir / "zhilian_cookies.json").write_text(
        json.dumps([{"name": "at", "value": "x"}]),
        encoding="utf-8",
    )

    import asyncio

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=AsyncMock())
    context.add_cookies = AsyncMock()
    context.cookies = AsyncMock(return_value=[{"name": "other"}])  # at/rt missing

    restored = asyncio.run(zhilian_browser._restore_cookies(context, profile_dir))
    assert restored is False
