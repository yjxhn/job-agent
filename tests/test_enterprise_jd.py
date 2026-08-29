"""Enterprise-platform JD fetching tests (T5-7).

Covers the shared base.PlatformAdapter.fetch_full_jd used by the five
enterprise adapters (tencent/netease/byd/naura/yofc): the lid guard, the
playwright call, the 5000-char cap and the empty/error fallbacks.
"""

import pytest

from agent_core.platforms.base import Job
from agent_core.platforms.byd import BydAdapter
from agent_core.platforms.naura import NauraAdapter
from agent_core.platforms.netease import NeteaseAdapter
from agent_core.platforms.tencent import TencentAdapter
from agent_core.platforms.yofc import YofcAdapter

ADAPTERS = [TencentAdapter(), NeteaseAdapter(), BydAdapter(), NauraAdapter(), YofcAdapter()]


def _job(lid=""):
    return Job(id="x", title="t", company="c", lid=lid)


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
async def test_fetch_full_jd_skips_without_lid(adapter):
    """No lid -> return '' without touching playwright."""
    from unittest.mock import patch

    with patch("agent_core.platforms.playwright_jd.fetch_jd_playwright") as mock_fetch:
        result = await adapter.fetch_full_jd(_job(lid=""), "cookies.json")
    assert result == ""
    mock_fetch.assert_not_called()


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
async def test_fetch_full_jd_skips_with_non_url_lid(adapter):
    from unittest.mock import patch

    with patch("agent_core.platforms.playwright_jd.fetch_jd_playwright") as mock_fetch:
        result = await adapter.fetch_full_jd(_job(lid="refid-123"), "cookies.json")
    assert result == ""
    mock_fetch.assert_not_called()


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
async def test_fetch_full_jd_returns_playwright_jd(adapter):
    """Valid lid -> playwright JD is returned (capped at 5000 chars)."""
    from unittest.mock import patch

    long_jd = "岗位职责" * 3000  # ~18000 chars, well over the cap

    async def _fake_fetch(url, platform, cookie_path, headless):
        assert url == "https://example.com/job/1"
        assert platform == adapter.name
        return long_jd

    with patch(
        "agent_core.platforms.playwright_jd.fetch_jd_playwright", side_effect=_fake_fetch
    ) as mock_fetch:
        result = await adapter.fetch_full_jd(_job(lid="https://example.com/job/1"), "c.json")
    assert len(result) == 5000
    assert mock_fetch.call_count == 1


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
async def test_fetch_full_jd_returns_empty_for_short_jd(adapter):
    """JD shorter than 50 chars is treated as a failed fetch."""
    from unittest.mock import patch

    async def _fake_fetch(url, platform, cookie_path, headless):
        return "太短"

    with patch("agent_core.platforms.playwright_jd.fetch_jd_playwright", side_effect=_fake_fetch):
        result = await adapter.fetch_full_jd(_job(lid="https://example.com/job/1"), "c.json")
    assert result == ""


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: a.name)
async def test_fetch_full_jd_returns_empty_on_playwright_error(adapter):
    """Playwright exception -> '' (logged, not raised)."""
    from unittest.mock import patch

    async def _boom(url, platform, cookie_path, headless):
        raise RuntimeError("playwright not installed")

    with patch("agent_core.platforms.playwright_jd.fetch_jd_playwright", side_effect=_boom):
        result = await adapter.fetch_full_jd(_job(lid="https://example.com/job/1"), "c.json")
    assert result == ""
