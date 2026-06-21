"""Tests for Boss直聘 platform adapter rate limiting and anti-bot handling."""

from unittest.mock import patch

import pytest

from agent_core.platforms.boss_zhipin import BossZhipinAdapter


@pytest.mark.asyncio
class TestBossRateLimit:
    """Test rate_limit_seconds configuration integration."""

    @patch("agent_core.platforms.boss_zhipin._load_cookies")
    @patch("agent_core.platforms.boss_zhipin._session_cookie_valid")
    async def test_rate_limit_from_config(self, mock_valid, mock_load, caplog):
        """Test that rate_limit_seconds from config is used instead of default."""
        mock_load.return_value = []
        mock_valid.return_value = True

        # Test with custom rate_limit_seconds
        adapter = BossZhipinAdapter(rate_limit_seconds=5.0)
        assert adapter._rate_limit_seconds == 5.0

        # Test with None (should use default)
        adapter_default = BossZhipinAdapter(rate_limit_seconds=None)
        assert adapter_default._rate_limit_seconds == 1.5

    @patch("agent_core.platforms.boss_zhipin._load_cookies")
    @patch("agent_core.platforms.boss_zhipin._session_cookie_valid")
    @patch("agent_core.platforms.boss_zhipin._notify_anti_bot")
    async def test_code_37_backoff_from_config(self, mock_notify, mock_valid, mock_load, caplog):
        """Test that code-37 triggers backoff with config value, not hardcoded 300."""
        mock_load.return_value = []
        mock_valid.return_value = True

        # Create adapter with custom rate_limit_seconds
        test_rate_limit = 10.0
        adapter = BossZhipinAdapter(rate_limit_seconds=test_rate_limit)

        # Mock API response with code 37
        mock_obj = {
            "code": 37,
            "message": "Anti-bot challenge required",
            "zpData": {"seed": "test123"}
        }

        with patch("agent_core.platforms.boss_zhipin.json.loads") as mock_json:
            mock_json.return_value = mock_obj

            _result = await adapter._search_keyword_api(
                keyword="test",
                city_code="100010000",
                cookie_str="test=123",
                max_pages=1
            )

        # Verify backoff uses the config value, not hardcoded 300
        assert adapter._ANTI_BOT_BACKOFF_SECONDS == test_rate_limit
        mock_notify.assert_called_once()
        assert len(caplog.records) > 0
        # Check log contains the config value
        backoff_logs = [r for r in caplog.records if "Backing off" in r.message]
        assert len(backoff_logs) > 0
        assert str(test_rate_limit) in backoff_logs[0].message

    @patch("agent_core.platforms.boss_zhipin._load_cookies")
    @patch("agent_core.platforms.boss_zhipin._session_cookie_valid")
    @patch("agent_core.platforms.boss_zhipin.json.loads")
    async def test_regular_request_rate_limit(self, mock_json, mock_valid, mock_load):
        """Test that regular API calls use the rate_limit_seconds from config."""
        mock_load.return_value = []
        mock_valid.return_value = True

        # Mock successful API response
        mock_obj = {
            "code": 0,
            "message": "Success",
            "zpData": {"jobList": []}
        }
        mock_json.return_value = mock_obj

        # Test with custom rate_limit_seconds
        test_rate_limit = 3.0
        adapter = BossZhipinAdapter(rate_limit_seconds=test_rate_limit)

        await adapter._search_keyword_api(
            keyword="test",
            city_code="100010000",
            cookie_str="test=123",
            max_pages=1
        )

        # Verify the rate_limit_seconds was stored
        assert adapter._rate_limit_seconds == test_rate_limit

    @patch("agent_core.platforms.boss_zhipin._load_cookies")
    @patch("agent_core.platforms.boss_zhipin._session_cookie_valid")
    @patch("agent_core.platforms.boss_zhipin.json.loads")
    async def test_default_rate_limit_when_none_provided(
        self, mock_json, mock_valid, mock_load, caplog,
    ):
        """Test that default rate_limit_seconds (1.5) is used when None is provided."""
        mock_load.return_value = []
        mock_valid.return_value = True

        # Mock successful API response
        mock_obj = {
            "code": 0,
            "message": "Success",
            "zpData": {"jobList": []}
        }
        mock_json.return_value = mock_obj

        # Create adapter without rate_limit_seconds parameter
        adapter = BossZhipinAdapter()

        # Should use default 1.5
        assert adapter._rate_limit_seconds == 1.5
        assert adapter._ANTI_BOT_BACKOFF_SECONDS == 300  # Default backoff
