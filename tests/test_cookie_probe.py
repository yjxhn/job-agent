"""Probe-path tests for cookie health checking (T5-6).

Previously only the file-only branch was covered; _probe_platform (real
search probe) had no tests.
"""

import json

import pytest

from agent_core.cookie_health import CookieStatus, PlatformCookieSpec, _probe_platform
from agent_core.platforms.base import Job


def _spec(cookie_file, needs_cookie=True, platform="boss_zhipin"):
    return PlatformCookieSpec(
        platform_key=platform,
        display_name=platform,
        needs_cookie=needs_cookie,
        critical_cookies={"wt2", "__zp_stoken__"},
        cookie_path=str(cookie_file),
    )


def _write_valid_cookie(path):
    path.write_text(
        json.dumps(
            [
                {"name": "wt2", "value": "tok", "expires": -1},
                {"name": "__zp_stoken__", "value": "stok", "expires": -1},
            ]
        ),
        encoding="utf-8",
    )


def _fake_jobs(n=2):
    return [Job(id=f"j{i}", title="测试", company="C") for i in range(n)]


async def test_probe_success_appends_jobs(tmp_path):
    cookie_file = tmp_path / "boss.json"
    _write_valid_cookie(cookie_file)
    spec = _spec(cookie_file)

    async def _fake_search(self, keywords, location, cookie_path, rate_limit_seconds):
        return _fake_jobs(2)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "agent_core.platforms.boss_zhipin.BossZhipinAdapter.search",
            _fake_search,
        )
        result = await _probe_platform(spec, "全国")

    assert result.status == CookieStatus.VALID
    assert any("探活成功: 返回 2 个职位" in d for d in result.details)


async def test_probe_zero_jobs_downgrades_to_unverified(tmp_path):
    cookie_file = tmp_path / "boss.json"
    _write_valid_cookie(cookie_file)
    spec = _spec(cookie_file)

    async def _fake_search(self, keywords, location, cookie_path, rate_limit_seconds):
        return []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "agent_core.platforms.boss_zhipin.BossZhipinAdapter.search",
            _fake_search,
        )
        result = await _probe_platform(spec, "全国")

    assert result.status == CookieStatus.UNVERIFIED
    assert any("探活返回 0 个职位" in d for d in result.details)


async def test_probe_exception_appends_failure(tmp_path):
    cookie_file = tmp_path / "boss.json"
    _write_valid_cookie(cookie_file)
    spec = _spec(cookie_file)

    async def _boom(self, keywords, location, cookie_path, rate_limit_seconds):
        raise RuntimeError("connection refused")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "agent_core.platforms.boss_zhipin.BossZhipinAdapter.search",
            _boom,
        )
        result = await _probe_platform(spec, "全国")

    assert any("探活失败" in d for d in result.details)


async def test_probe_skipped_without_cookie_file(tmp_path):
    spec = _spec(tmp_path / "missing.json")
    result = await _probe_platform(spec, "全国")
    # no probe detail appended (no adapter constructed)
    assert not any("探活" in d for d in result.details)
    assert result.status in (CookieStatus.MISSING, CookieStatus.EXPIRED)


async def test_probe_skipped_for_public_platform(tmp_path):
    spec = _spec(tmp_path / "x.json", needs_cookie=False, platform="tencent")
    result = await _probe_platform(spec, "全国")
    assert result.status == CookieStatus.NO_COOKIE_NEEDED
