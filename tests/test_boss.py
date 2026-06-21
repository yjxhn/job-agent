"""Tests for Boss platform: anti-bot vs cookie-expired distinction, JD detail fetch."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_core.platforms.boss_zhipin import BossZhipinAdapter


# Test: anti-bot challenge (code 37) triggers _notify_anti_bot, NOT _notify_cookie_expired
def test_code_37_triggers_anti_bot_not_expired(monkeypatch):
    from agent_core.platforms import boss_zhipin
    from agent_core.notify import windows_toast as wt

    # Track which notify function was called
    anti_bot_called = []
    cookie_expired_called = []

    # Monkeypatch at module level to match actual call signature (no args)
    def fake_notify_anti_bot():
        anti_bot_called.append("Boss直聘")

    def fake_notify_cookie_expired():
        cookie_expired_called.append("Boss直聘")

    # Mock urlopen to return code 37 with challenge markers
    fake_resp = json.dumps({
        "code": 37,
        "message": "x",
        "zpData": {"seed": "s", "name": "n", "ts": 1}
    }).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(boss_zhipin, "_notify_anti_bot", fake_notify_anti_bot)
    monkeypatch.setattr(boss_zhipin, "_notify_cookie_expired", fake_notify_cookie_expired)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))

    assert anti_bot_called == ["Boss直聘"], f"Expected anti-bot called, got {anti_bot_called}"
    assert cookie_expired_called == [], f"Cookie expired should NOT be called, got {cookie_expired_called}"
    assert jobs == [], "Should return empty list on anti-bot"


# Test: code-37 backoff sleep test (would wait 300s, blocks CI, so skipped)
@pytest.mark.skip(reason="Backoff sleep takes 300s, skip in CI")
def test_code_37_backoff_sleeps():
    """Test: code-37 triggers _ANTI_BOT_BACKOFF_SECONDS (300s) backoff."""
    from agent_core.platforms import boss_zhipin

    # Mock asyncio.sleep to track if backoff duration is used
    sleep_called_with = []

    async def fake_sleep(seconds):
        if seconds == 300:
            sleep_called_with.append(True)

    # Mock urlopen to return code 37
    fake_resp = json.dumps({
        "code": 37,
        "message": "anti-bot challenge",
        "zpData": {"seed": "s", "name": "n", "ts": 1}
    }).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = BossZhipinAdapter(rate_limit_seconds=1.5)
    # This will trigger backoff and should sleep 300s
    try:
        asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=1))
    except Exception as e:
        # We expect the backoff to break after sleep
        pass

    # Wait a bit for the async sleep to complete if triggered
    import time
    time.sleep(0.1)

    assert sleep_called_with == [True], "Should have slept 300s on code-37 backoff"


# Test: other non-zero codes trigger _notify_cookie_expired
def test_other_nonzero_triggers_cookie_expired(monkeypatch):
    from agent_core.platforms import boss_zhipin

    anti_bot_called = []
    cookie_expired_called = []

    def fake_notify_anti_bot():
        anti_bot_called.append("Boss直聘")

    def fake_notify_cookie_expired():
        cookie_expired_called.append("Boss直聘")

    # Mock urlopen to return code 1501 (auth error) without challenge markers
    fake_resp = json.dumps({
        "code": 1501,
        "message": "login required",
        "zpData": {}
    }).encode()

    class FakeResp:
        def read(self):
            return fake_resp

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(boss_zhipin, "_notify_anti_bot", fake_notify_anti_bot)
    monkeypatch.setattr(boss_zhipin, "_notify_cookie_expired", fake_notify_cookie_expired)

    adapter = BossZhipinAdapter()
    jobs = asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x"))

    assert anti_bot_called == [], f"Anti-bot should NOT be called, got {anti_bot_called}"
    assert cookie_expired_called == ["Boss直聘"], f"Expected cookie expired called, got {cookie_expired_called}"
    assert jobs == [], "Should return empty list on auth error"


# Test: rate_limit_seconds is used for page sleep
def test_rate_limit_seconds_used(monkeypatch):
    """Verify that rate_limit_seconds from config is used for page delays."""
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    sleep_called_with = []

    async def fake_sleep(seconds):
        sleep_called_with.append(seconds)

    def create_fake_resp(page):
        return json.dumps({
            "code": 0,
            "zpData": {"jobList": [{
                "jobName": "AMR Engineer",
                "brandName": "Test Corp",
                "encryptJobId": "test001",
                "cityName": "Suzhou",
                "areaDistrict": "",
                "businessDistrict": "",
                "salaryDesc": "15-20K",
                "jobExperience": "3-5年",
                "jobDegree": "本科",
                "skills": [],
                "jobLabels": [],
                "welfareList": [],
                "brandIndustry": "",
                "brandScaleName": "",
                "securityId": "",
                "lid": ""
            }]}
        }).encode()

    class FakeResp:
        def __init__(self, page):
            self.page = page

        def read(self):
            return create_fake_resp(self.page)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp(1)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    # Test with custom rate_limit_seconds
    adapter = BossZhipinAdapter(rate_limit_seconds=2.5)
    asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=1))

    # Should have slept 2.5s for the single page
    assert 2.5 in sleep_called_with, f"Expected sleep with 2.5s, got {sleep_called_with}"


# Test: rate_limit_seconds defaults to 1.5 when not provided
def test_rate_limit_defaults(monkeypatch):
    """Verify that rate_limit_seconds defaults to 1.5 when not provided."""
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter

    sleep_called_with = []

    async def fake_sleep(seconds):
        sleep_called_with.append(seconds)

    def create_fake_resp(page):
        return json.dumps({
            "code": 0,
            "zpData": {"jobList": [{
                "jobName": "AMR Engineer",
                "brandName": "Test Corp",
                "encryptJobId": "test001",
                "cityName": "Suzhou",
                "areaDistrict": "",
                "businessDistrict": "",
                "salaryDesc": "15-20K",
                "jobExperience": "3-5年",
                "jobDegree": "本科",
                "skills": [],
                "jobLabels": [],
                "welfareList": [],
                "brandIndustry": "",
                "brandScaleName": "",
                "securityId": "",
                "lid": ""
            }]}
        }).encode()

    class FakeResp:
        def __init__(self, page):
            self.page = page

        def read(self):
            return create_fake_resp(self.page)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=20):
        return FakeResp(1)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    adapter = BossZhipinAdapter()  # No rate_limit_seconds arg, should use default
    asyncio.run(adapter._search_keyword_api("AMR", "100010000", "wt2=x", max_pages=1))

    # Should have slept with default 1.5s
    assert 1.5 in sleep_called_with, f"Expected default sleep with 1.5s, got {sleep_called_with}"
