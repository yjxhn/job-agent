"""Misc coverage: providers, platform stubs, search integration, base.Job."""

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


# ---------- thinking mode ----------


def test_thinking_disabled_by_default_in_config():
    """thinking.enabled defaults to False — backward compatible."""
    from agent_core.config import ThinkingConfig

    tc = ThinkingConfig()
    assert tc.enabled is False
    assert tc.effort == "high"


def test_thinking_effort_validation():
    """effort must be one of the accepted values."""
    from agent_core.config import ThinkingConfig

    ThinkingConfig(effort="high")
    ThinkingConfig(effort="max")
    ThinkingConfig(effort="low")
    ThinkingConfig(effort="medium")
    ThinkingConfig(effort="xhigh")
    with pytest.raises(ValueError, match="thinking.effort"):
        ThinkingConfig(effort="invalid")


def test_thinking_disabled_no_reasoning_kwargs():
    """When thinking_enabled=False, _thinking_kwargs returns empty dict."""
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", thinking_enabled=False)
    assert p._thinking_kwargs() == {}


def test_thinking_enabled_adds_reasoning_kwargs():
    """When thinking_enabled=True, _thinking_kwargs returns reasoning params."""
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", thinking_enabled=True, thinking_effort="max")
    kw = p._thinking_kwargs()
    assert kw["reasoning_effort"] == "max"
    assert kw["extra_body"] == {"thinking": {"type": "enabled"}}


def test_chat_no_temperature_when_thinking(monkeypatch):
    """chat() with thinking enabled omits temperature from API call."""
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", thinking_enabled=True, thinking_effort="high")
    p.client = MagicMock()
    mock_msg = MagicMock(content="hi", reasoning_content="Let me think...")
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=mock_msg)])
    )
    asyncio.run(p.chat(messages=[{"role": "user", "content": "x"}], temperature=0.7))
    kw = p.client.chat.completions.create.call_args.kwargs
    assert "temperature" not in kw
    assert kw["reasoning_effort"] == "high"
    assert kw["extra_body"] == {"thinking": {"type": "enabled"}}


def test_chat_with_tools_captures_reasoning_content():
    """chat_with_tools with thinking enabled captures reasoning_content in ChatResponse."""
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", thinking_enabled=True, thinking_effort="high")
    p.client = MagicMock()
    fake_tool_call = MagicMock()
    fake_tool_call.id = "call_1"
    fake_tool_call.function.name = "search_jobs"
    fake_tool_call.function.arguments = '{"keywords":["Python"]}'
    fake_msg = MagicMock()
    fake_msg.content = "Let me search that for you."
    fake_msg.reasoning_content = "User wants to search jobs. I should call search_jobs."
    fake_msg.tool_calls = [fake_tool_call]
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    p.client.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[fake_choice]))
    resp = asyncio.run(
        p.chat_with_tools(
            messages=[{"role": "user", "content": "find Python jobs"}],
            tools=[{"type": "function", "function": {"name": "search_jobs", "parameters": {}}}],
        )
    )
    assert resp.reasoning_content is not None
    assert "search_jobs" in resp.reasoning_content
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "search_jobs"
    assert resp.tool_calls[0].id == "call_1"


def test_chat_with_tools_no_reasoning_when_thinking_disabled():
    """chat_with_tools with thinking disabled: reasoning_content is None, temperature present."""
    from agent_core.llm.providers import DeepSeekProvider

    p = DeepSeekProvider(api_key="k", thinking_enabled=False)
    p.client = MagicMock()
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
    )
    resp = asyncio.run(
        p.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "search_jobs", "parameters": {}}}],
            temperature=0.7,
        )
    )
    assert resp.reasoning_content is None
    kw = p.client.chat.completions.create.call_args.kwargs
    assert kw["temperature"] == 0.7
    assert "reasoning_effort" not in kw
    assert "extra_body" not in kw


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


@pytest.mark.asyncio
async def test_call_llm_with_retry_times_out():
    """LLM 长时间不返回时必须有总超时，不能无限等。"""
    from agent_core.llm.providers import call_llm_with_retry

    provider = AsyncMock()

    async def slow_chat(*a, **kw):
        await asyncio.sleep(10)
        return "late"

    provider.chat = slow_chat
    with pytest.raises(TimeoutError):
        await call_llm_with_retry(
            provider, messages=[{"role": "user", "content": "hi"}], timeout=0.01
        )


# ---------- platform stubs ----------


def test_zhilian_no_cookie_returns_empty(monkeypatch):
    """Zhilian adapter returns empty list when no cookie is available."""
    from agent_core.platforms.zhilian import ZhilianAdapter

    # Mock browser path -> empty (forces HTTP fallback)
    class _MockBrowser:
        def __init__(self, *a, **kw):
            pass

        async def search(self, *a, **kw):
            return []

        async def close(self):
            pass

    async def _mock_get_browser(profile_dir="data/zhilian_browser_profile", headless=False):
        return _MockBrowser()

    monkeypatch.setattr(
        "agent_core.platforms.zhilian_browser.get_browser",
        _mock_get_browser,
    )

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

    jobs = asyncio.run(search.search_all(cfg, directions=["equipment_amr"], keywords=["AMR"]))
    assert len(jobs) >= 1
    assert jobs[0].title == "AMR"


def test_search_all_empty_when_no_platforms(cfg, monkeypatch):
    from agent_core.pipeline import search

    # Disable all platforms
    for p in cfg.platforms.values():
        p.enabled = False
    jobs = asyncio.run(search.search_all(cfg, directions=["equipment_amr"], keywords=["AMR"]))
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
