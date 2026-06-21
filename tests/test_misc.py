"""Misc coverage: providers, cron_parser, platform stubs, search integration, base.Job."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_core.config import load_config
from agent_core.platforms.base import Job


@pytest.fixture
def cfg():
    return load_config("config.yaml")


def _now():
    return datetime.now(UTC)


# ---------- cron_parser ----------


def test_cron_parser_parse_units():
    from agent_core.scheduler.cron_parser import parse

    assert parse("6h") == 6
    assert parse("1d") == 24
    assert parse("90m") == 1  # 90 // 60
    assert parse("5") == 5
    assert parse("garbage") == 6  # default fallback


def test_cron_parser_fmt():
    from agent_core.scheduler.cron_parser import fmt

    assert fmt(24) == "1d"
    assert fmt(48) == "2d"
    assert fmt(6) == "6h"


# ---------- providers ----------


def test_deepseek_provider_chat_passes_response_format():
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", base_url="http://x", model="m")
    p.client = MagicMock()
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="hi"))])
    )
    out = asyncio.run(
        p.chat(messages=[{"role": "user", "content": "x"}], response_format={"type": "json_object"})
    )
    assert out == "hi"
    kw = p.client.chat.completions.create.call_args.kwargs
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["model"] == "m"


def test_deepseek_provider_chat_omits_response_format_when_none():
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", base_url="http://x", model="m")
    p.client = MagicMock()
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
    )
    asyncio.run(p.chat(messages=[{"role": "user", "content": "x"}]))
    kw = p.client.chat.completions.create.call_args.kwargs
    assert "response_format" not in kw


def test_create_provider_unsupported_raises():
    from agent_core.llm.providers import create_provider

    cfg = MagicMock()
    cfg.llm.provider = "unknown"
    with pytest.raises(ValueError):
        create_provider(cfg)


def test_create_provider_deepseek(monkeypatch):
    from agent_core.llm.providers import DeepSeekProvider, create_provider

    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    cfg = load_config("config.yaml")
    p = create_provider(cfg)
    assert isinstance(p, DeepSeekProvider)


# ---------- call_llm_with_retry ----------


@pytest.mark.asyncio
async def test_call_llm_with_retry_success_on_first_attempt():
    """No retries needed when first call succeeds."""
    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()
    provider.chat = AsyncMock(return_value="ok")

    result = await call_llm_with_retry(provider, messages=[{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert provider.chat.call_count == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_handles_429_then_succeeds():
    """First call 429, second succeeds — should retry once."""
    from openai import RateLimitError

    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()
    provider.chat = AsyncMock()
    provider.chat.side_effect = [
        RateLimitError("rate limited", response=MagicMock(), body=None),
        "ok",
    ]

    result = await call_llm_with_retry(provider, messages=[{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert provider.chat.call_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_retry_handles_429_with_api_status_error():
    """APIStatusError with status_code=429 treated like RateLimitError."""
    from openai import APIStatusError

    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()
    provider.chat = AsyncMock()
    provider.chat.side_effect = [
        APIStatusError("429", response=MagicMock(status_code=429), body=None),
        "ok",
    ]

    result = await call_llm_with_retry(provider, messages=[{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert provider.chat.call_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_retry_timeout_then_succeeds():
    """Timeout on first, success on second."""
    from openai import APITimeoutError

    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()
    provider.chat = AsyncMock()
    provider.chat.side_effect = [
        APITimeoutError("timeout"),
        "ok",
    ]

    result = await call_llm_with_retry(provider, messages=[{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert provider.chat.call_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_retry_exhausted_raises():
    """All 3 retries fail with RateLimitError — should raise."""
    from openai import RateLimitError

    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()
    provider.chat = AsyncMock()
    provider.chat.side_effect = RateLimitError("rate limited", response=MagicMock(), body=None)

    with pytest.raises(RateLimitError):
        await call_llm_with_retry(provider, messages=[{"role": "user", "content": "hi"}])
    assert provider.chat.call_count == 3


@pytest.mark.asyncio
async def test_call_llm_with_retry_non_retryable_error_passes_through():
    """Non-retryable errors should propagate immediately (no retry)."""
    from openai import APIStatusError

    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()
    provider.chat = AsyncMock()
    provider.chat.side_effect = APIStatusError(
        "500 Internal Server Error", response=MagicMock(status_code=500), body=None
    )

    with pytest.raises(APIStatusError):
        await call_llm_with_retry(provider, messages=[{"role": "user", "content": "hi"}])
    assert provider.chat.call_count == 1  # no retry for non-429


# ---------- platform stubs ----------


def test_zhilian_no_cookie_returns_empty():
    """Zhilian adapter returns empty list when no cookie is available."""
    from agent_core.platforms.zhilian import ZhilianAdapter

    jobs = asyncio.run(ZhilianAdapter().search(["x"], "全国"))
    assert jobs == [], "Should return empty list when no cookie"


def test_zhilian_normalize():
    from agent_core.platforms.zhilian import ZhilianAdapter

    j = ZhilianAdapter().normalize(
        {"id": "1", "title": "T", "company": "C", "location": "L", "url": "http://x"}
    )
    assert j.title == "T"
    assert j.urls["zhilian"] == "http://x"


# ---------- search.search_all integration (mocked adapters) ----------


def test_search_all_runs_adapters_and_dedups(cfg, monkeypatch):
    from agent_core.pipeline import search
    from agent_core.platforms.boss_zhipin import BossZhipinAdapter
    from agent_core.platforms.liepin import LiepinAdapter

    fake_jobs = [
        Job(
            id="1",
            title="AMR",
            company="A",
            company_normalized="a",
            platforms=["boss_zhipin"],
            urls={"boss_zhipin": "http://1"},
            first_seen=_now(),
            last_seen=_now(),
        )
    ]

    async def fake_search(
        self, keywords, location, cookie_path=None, headless=False, rate_limit_seconds=None
    ):
        return list(fake_jobs)

    monkeypatch.setattr(BossZhipinAdapter, "search", fake_search)
    monkeypatch.setattr(LiepinAdapter, "search", fake_search)

    jobs = asyncio.run(search.search_all(cfg, directions=["equipment_amr"]))
    assert len(jobs) >= 1
    assert jobs[0].title == "AMR"


def test_search_all_empty_when_no_platforms(cfg, monkeypatch):
    from agent_core.pipeline import search

    # Disable all platforms
    for p in cfg.platforms.values():
        p.enabled = False
    jobs = asyncio.run(search.search_all(cfg, directions=["equipment_amr"]))
    assert jobs == []


# ---------- base.Job ----------


def test_job_dedup_key_strips_parenthetical():
    j = Job(id="1", title="AMR工程师（资深）", company="A", company_normalized="a")
    k = j.dedup_key()
    assert "（资深）" not in k
    assert k.startswith("a|")


def test_job_to_storage_from_storage_roundtrip():
    now = datetime.now(UTC)
    j = Job(
        id="1",
        title="T",
        company="C",
        company_normalized="c",
        direction="equipment_amr",
        platforms=["boss_zhipin"],
        urls={"boss_zhipin": "http://x"},
        first_seen=now,
        last_seen=now,
    )
    rec = j.to_storage()
    j2 = Job.from_storage(rec)
    assert j2.title == "T"
    assert j2.direction == "equipment_amr"
    assert j2.company_normalized == "c"


def test_job_from_storage_accepts_db_row_dict():
    from agent_core.platforms.base import Job

    row = {
        "id": "1",
        "title": "T",
        "company": "C",
        "company_normalized": "c",
        "location": "",
        "salary_min": None,
        "salary_max": None,
        "description": "",
        "platforms": "[]",
        "urls": "{}",
        "direction": "d",
        "first_seen": "",
        "last_seen": "",
        "is_new": 1,
    }
    j = Job.from_storage(row)
    assert j.title == "T" and j.direction == "d"
