"""Tests for agent_core/cookie_health.py — cookie health checks and regrab guides."""

import json
import time
from pathlib import Path

import pytest

from agent_core.config import Config, PlatformConfig
from agent_core.cookie_health import (
    PLATFORM_SPECS,
    CookieHealthResult,
    CookieStatus,
    _check_single_platform,
    _format_expiry_time,
    _load_cookie_file,
    _parse_cookie_expiry,
    check_cookies,
    diagnose_empty_results,
    get_regrab_guide,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cookie(name: str, expires: float = -1) -> dict:
    return {
        "name": name,
        "value": "placeholder",
        "domain": ".example.com",
        "path": "/",
        "expires": expires,
        "httpOnly": True,
        "secure": False,
        "sameSite": "Lax",
    }


def _write_cookie_file(path: Path, cookies: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# _parse_cookie_expiry
# ---------------------------------------------------------------------------


def test_parse_cookie_expiry_session():
    c = {"name": "s", "expires": -1}
    exp, desc = _parse_cookie_expiry(c)
    assert exp == -1
    assert desc == "session"


def test_parse_cookie_expiry_future():
    ts = time.time() + 86400
    c = {"name": "f", "expires": ts}
    exp, desc = _parse_cookie_expiry(c)
    assert exp == ts
    assert desc == ""


def test_parse_cookie_expiry_expirationdate():
    ts = time.time() + 86400
    c = {"name": "ed", "expirationDate": ts}
    exp, desc = _parse_cookie_expiry(c)
    assert exp == ts


def test_parse_cookie_expiry_none():
    c = {"name": "n"}
    exp, desc = _parse_cookie_expiry(c)
    assert exp == -1
    assert desc == "session"


# ---------------------------------------------------------------------------
# _load_cookie_file
# ---------------------------------------------------------------------------


def test_load_cookie_file_missing(tmp_path):
    cookies = _load_cookie_file(str(tmp_path / "nonexistent.json"))
    assert cookies is None


def test_load_cookie_file_valid(tmp_path):
    p = tmp_path / "cookies.json"
    _write_cookie_file(p, [_make_cookie("a")])
    cookies = _load_cookie_file(str(p))
    assert cookies is not None
    assert len(cookies) == 1
    assert cookies[0]["name"] == "a"


def test_load_cookie_file_not_a_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    cookies = _load_cookie_file(str(p))
    assert cookies is None


# ---------------------------------------------------------------------------
# _check_single_platform — no cookie needed
# ---------------------------------------------------------------------------


def test_check_single_platform_no_cookie_needed():
    spec = PLATFORM_SPECS["tencent"]
    r = _check_single_platform(spec)
    assert r.status == CookieStatus.NO_COOKIE_NEEDED
    assert "公开API" in r.details[0]


# ---------------------------------------------------------------------------
# _check_single_platform — missing file
# ---------------------------------------------------------------------------


def test_check_single_platform_missing():
    spec = PLATFORM_SPECS["boss_zhipin"]
    import copy

    s = copy.copy(spec)
    s.cookie_path = "/nonexistent/path.json"
    r = _check_single_platform(s)
    assert r.status == CookieStatus.MISSING
    assert "文件不存在" in r.details[0]


# ---------------------------------------------------------------------------
# _check_single_platform — valid
# ---------------------------------------------------------------------------


def _make_boss_cookies(far_future: float) -> list[dict]:
    """Make a full set of Boss critical cookies."""
    return [
        _make_cookie("wt2", far_future),
        _make_cookie("__zp_stoken__", far_future),
    ]


def test_check_single_platform_valid(tmp_path):
    p = tmp_path / "cookies.json"
    far_future = time.time() + 365 * 86400
    _write_cookie_file(p, _make_boss_cookies(far_future))

    spec = PLATFORM_SPECS["boss_zhipin"]
    import copy

    s = copy.copy(spec)
    s.cookie_path = str(p)
    r = _check_single_platform(s)
    assert r.status == CookieStatus.VALID


# ---------------------------------------------------------------------------
# _check_single_platform -- expired critical cookie
# ---------------------------------------------------------------------------


def test_check_single_platform_expired(tmp_path):
    p = tmp_path / "cookies.json"
    past = time.time() - 86400  # expired yesterday
    _write_cookie_file(p, _make_boss_cookies(past))

    spec = PLATFORM_SPECS["boss_zhipin"]
    import copy

    s = copy.copy(spec)
    s.cookie_path = str(p)
    r = _check_single_platform(s)
    assert r.status == CookieStatus.EXPIRED
    assert any("已过期" in d for d in r.details)


# ---------------------------------------------------------------------------
# _check_single_platform -- expiring soon
# ---------------------------------------------------------------------------


def test_check_single_platform_expiring_soon(tmp_path):
    p = tmp_path / "cookies.json"
    # expires in 3 days (within 7-day warning window)
    soon = time.time() + 3 * 86400
    _write_cookie_file(p, _make_boss_cookies(soon))

    spec = PLATFORM_SPECS["boss_zhipin"]
    import copy

    s = copy.copy(spec)
    s.cookie_path = str(p)
    r = _check_single_platform(s)
    assert r.status == CookieStatus.EXPIRING_SOON
    assert any("天后过期" in d for d in r.details)


# ---------------------------------------------------------------------------
# _check_single_platform -- missing critical cookie
# ---------------------------------------------------------------------------


def test_check_single_platform_missing_critical_cookie(tmp_path):
    p = tmp_path / "cookies.json"
    far_future = time.time() + 365 * 86400
    # Provide wt2 but NOT __zp_stoken__ -- one missing critical cookie
    _write_cookie_file(p, [_make_cookie("wt2", far_future)])

    spec = PLATFORM_SPECS["boss_zhipin"]
    import copy

    s = copy.copy(spec)
    s.cookie_path = str(p)
    r = _check_single_platform(s)
    assert r.status == CookieStatus.EXPIRED  # missing critical = expired
    assert any("缺失" in d for d in r.details)


# ---------------------------------------------------------------------------
# _check_single_platform -- session cookie (no explicit expiry)
# ---------------------------------------------------------------------------


def test_check_single_platform_session_cookie(tmp_path):
    p = tmp_path / "cookies.json"
    # Both cookies as session (no expiry)
    _write_cookie_file(p, [_make_cookie("wt2", -1), _make_cookie("__zp_stoken__", -1)])

    spec = PLATFORM_SPECS["boss_zhipin"]
    import copy

    s = copy.copy(spec)
    s.cookie_path = str(p)
    r = _check_single_platform(s)
    assert r.status == CookieStatus.VALID  # session cookies treated as valid
    assert any("session" in d for d in r.details)


# ---------------------------------------------------------------------------
# get_regrab_guide
# ---------------------------------------------------------------------------


def test_regrab_guide_boss_has_steps():
    guide = get_regrab_guide("boss_zhipin")
    assert "zhipin.com" in guide
    assert "EditThisCookie" in guide
    assert "boss_zhipin.json" in guide


def test_regrab_guide_liepin_has_steps():
    guide = get_regrab_guide("liepin")
    assert "liepin.com" in guide
    assert "lt_auth" in guide


def test_regrab_guide_zhilian_has_steps():
    guide = get_regrab_guide("zhilian")
    assert "zhaopin.com" in guide
    assert "login --platform zhilian" in guide  # browser-profile login (not cURL/at-rt)


def test_regrab_guide_public_api():
    guide = get_regrab_guide("tencent")
    assert "无需 cookie" in guide


def test_regrab_guide_unknown_platform():
    guide = get_regrab_guide("nonexistent")
    assert "无重抓指引" in guide


# ---------------------------------------------------------------------------
# check_cookies (async, file-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_cookies_no_probe_excludes_public():
    """Public API platforms should be marked NO_COOKIE_NEEDED."""
    config = Config(
        platforms={
            "tencent": PlatformConfig(enabled=True, cookie_path=""),
            "netease": PlatformConfig(enabled=True, cookie_path=""),
        },
        directions={},
        company_aliases={},
    )
    results = await check_cookies(config, probe=False)
    for r in results:
        assert r.status == CookieStatus.NO_COOKIE_NEEDED


@pytest.mark.asyncio
async def test_check_cookies_missing_file_reports_missing(tmp_path):
    boss_path = tmp_path / "cookies" / "boss_zhipin.json"
    boss_path.parent.mkdir(parents=True, exist_ok=True)
    # Don't create the file
    config = Config(
        platforms={
            "boss_zhipin": PlatformConfig(enabled=True, cookie_path=str(boss_path)),
        },
        directions={},
        company_aliases={},
    )
    results = await check_cookies(config, probe=False)
    assert len(results) == 1
    assert results[0].status == CookieStatus.MISSING
    assert results[0].regrab_guide


@pytest.mark.asyncio
async def test_check_cookies_valid_file_reports_valid(tmp_path):
    boss_path = tmp_path / "cookies" / "boss_zhipin.json"
    boss_path.parent.mkdir(parents=True, exist_ok=True)
    far_future = time.time() + 365 * 86400
    _write_cookie_file(
        boss_path,
        [
            _make_cookie("wt2", far_future),
            _make_cookie("__zp_stoken__", far_future),
        ],
    )

    config = Config(
        platforms={
            "boss_zhipin": PlatformConfig(enabled=True, cookie_path=str(boss_path)),
        },
        directions={},
        company_aliases={},
    )
    results = await check_cookies(config, probe=False)
    assert len(results) == 1
    assert results[0].status == CookieStatus.VALID


@pytest.mark.asyncio
async def test_check_cookies_skips_disabled():
    config = Config(
        platforms={
            "boss_zhipin": PlatformConfig(enabled=False, cookie_path=""),
        },
        directions={},
        company_aliases={},
    )
    results = await check_cookies(config, probe=False)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_check_cookies_unknown_platform_handled_gracefully():
    config = Config(
        platforms={
            "some_unknown": PlatformConfig(enabled=True, cookie_path=""),
        },
        directions={},
        company_aliases={},
    )
    results = await check_cookies(config, probe=False)
    assert len(results) == 1
    assert results[0].status == CookieStatus.UNVERIFIED
    assert "未知平台" in results[0].details[0]


# ---------------------------------------------------------------------------
# diagnose_empty_results
# ---------------------------------------------------------------------------


def test_diagnose_empty_results_no_issues():
    """With no cookie-using platforms, no diagnosis."""
    config = Config(
        platforms={
            "tencent": PlatformConfig(enabled=True, cookie_path=""),
        },
        directions={},
        company_aliases={},
    )
    result = diagnose_empty_results(config)
    assert result is None


def test_diagnose_empty_results_with_issues(tmp_path):
    """Missing cookie file should trigger diagnosis."""
    boss_path = tmp_path / "boss_zhipin.json"
    # Don't create file

    config = Config(
        platforms={
            "boss_zhipin": PlatformConfig(enabled=True, cookie_path=str(boss_path)),
        },
        directions={},
        company_aliases={},
    )
    result = diagnose_empty_results(config)
    assert result is not None
    assert "cookie 问题" in result
    assert "Boss直聘" in result
    assert "缺失" in result


# ---------------------------------------------------------------------------
# Data class properties
# ---------------------------------------------------------------------------


def test_status_icon():
    r = CookieHealthResult(
        platform_key="test",
        display_name="test",
        status=CookieStatus.VALID,
        file_exists=True,
        needs_cookie=True,
    )
    assert r.status_icon == ("✅")  # ✅

    r.status = CookieStatus.EXPIRED
    assert r.status_icon == ("❌")  # ❌


def test_status_label():
    r = CookieHealthResult(
        platform_key="test",
        display_name="test",
        status=CookieStatus.NO_COOKIE_NEEDED,
        file_exists=False,
        needs_cookie=False,
    )
    assert r.status_label == ("无需cookie")  # 无需cookie


# ---------------------------------------------------------------------------
# _format_expiry_time
# ---------------------------------------------------------------------------


def test_format_expiry_time():
    # Use a known timestamp
    import datetime

    ts = datetime.datetime(2026, 12, 25, 10, 30).timestamp()
    formatted = _format_expiry_time(ts)
    assert "2026-12-25" in formatted


# ---------------------------------------------------------------------------
# PLATFORM_SPECS consistency
# ---------------------------------------------------------------------------


def test_platform_specs_have_all_config_platforms():
    """Every platform key in PLATFORM_SPECS used in config.yaml should be present."""
    expected = {"boss_zhipin", "liepin", "zhilian", "tencent", "netease"}
    assert set(PLATFORM_SPECS.keys()) >= expected


def test_cookie_platforms_have_regrab_guides():
    """All platforms that need cookies must have regrab guides."""
    for key, spec in PLATFORM_SPECS.items():
        if spec.needs_cookie:
            guide = get_regrab_guide(key)
            assert len(guide) > 20, f"{key} regrab guide too short"
            # zhilian uses cURL-based guide, not EditThisCookie
            assert (
                "EditThisCookie" in guide or "cURL" in guide or key in ("zhilian",)
            ), f"{key} missing extraction method mention"


def test_cookie_platforms_have_critical_cookies():
    for key, spec in PLATFORM_SPECS.items():
        if spec.needs_cookie:
            assert (
                len(spec.critical_cookies) > 0
            ), f"{key} needs cookie but has no critical cookies defined"
            assert spec.cookie_path, f"{key} missing cookie_path"
