"""Additional unit tests for agent_core.llm.providers.

All HTTP/OpenAI SDK interactions are mocked.  These tests intentionally
avoid real network, real API keys, and real LLM calls.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIStatusError, RateLimitError

from agent_core.config import Config, LLMConfig, ThinkingConfig
from agent_core.llm.providers import (
    DeepSeekProvider,
    _call_with_retry,
    _clean_surrogates,
    _sanitize_response,
    call_llm_with_reasoning_retry,
    call_llm_with_retry,
    call_llm_with_tools_retry,
    create_provider,
)

# ---------------------------------------------------------------------------
# _clean_surrogates
# ---------------------------------------------------------------------------


def test_clean_surrogates_empty_and_clean():
    assert _clean_surrogates("") == ""
    assert _clean_surrogates("plain text") == "plain text"


def test_clean_surrogates_replaces_lone_surrogates():
    dirty = "bad \udc80\udcff end"
    cleaned = _clean_surrogates(dirty)
    assert "\udc80" not in cleaned
    assert "\udcff" not in cleaned
    assert "\ufffd" in cleaned


# ---------------------------------------------------------------------------
# _sanitize_response
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, headers, body=b"", read_error=None):
        self.headers = headers
        self.body = body
        self.read_error = read_error
        self._content = b"original"
        self.read_called = False

    async def aread(self):
        self.read_called = True
        if self.read_error:
            raise self.read_error
        return self.body


@pytest.mark.asyncio
async def test_sanitize_response_json_cleans_surrogates():
    resp = _FakeResponse({"content-type": "application/json"}, body=b'{"x":"\x80"}')
    await _sanitize_response(resp)
    assert resp._content == '{"x":"\ufffd"}'.encode()


@pytest.mark.asyncio
async def test_sanitize_response_non_json_skips_read():
    resp = _FakeResponse({"content-type": "text/plain"}, body=b"hello")
    await _sanitize_response(resp)
    assert resp.read_called is False
    assert resp._content == b"original"


@pytest.mark.asyncio
async def test_sanitize_response_exception_is_swallowed():
    resp = _FakeResponse(
        {"content-type": "application/json"}, body=b"{}", read_error=RuntimeError("boom")
    )
    await _sanitize_response(resp)  # must not raise
    assert resp._content == b"original"


# ---------------------------------------------------------------------------
# DeepSeekProvider.chat_with_reasoning
# ---------------------------------------------------------------------------


def _provider_with_client(**provider_kwargs):
    p = DeepSeekProvider(api_key="k", **provider_kwargs)
    p.client = MagicMock()
    return p


def test_chat_with_reasoning_disabled_returns_empty_reasoning():
    p = _provider_with_client(thinking_enabled=False)
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="answer", reasoning_content="ignored"))]
        )
    )

    content, reasoning = asyncio.run(
        p.chat_with_reasoning(messages=[{"role": "user", "content": "hi"}])
    )

    assert content == "answer"
    assert reasoning == ""
    kw = p.client.chat.completions.create.call_args.kwargs
    assert kw["temperature"] == 0.7
    assert "reasoning_effort" not in kw


def test_chat_with_reasoning_enabled_returns_reasoning():
    p = _provider_with_client(thinking_enabled=True, thinking_effort="max")
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="answer", reasoning_content="chain"))]
        )
    )

    content, reasoning = asyncio.run(
        p.chat_with_reasoning(messages=[{"role": "user", "content": "hi"}])
    )

    assert content == "answer"
    assert reasoning == "chain"
    kw = p.client.chat.completions.create.call_args.kwargs
    assert kw["reasoning_effort"] == "max"
    assert "temperature" not in kw


def test_chat_with_reasoning_enabled_empty_reasoning():
    p = _provider_with_client(thinking_enabled=True)
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="answer", reasoning_content=None))]
        )
    )

    content, reasoning = asyncio.run(
        p.chat_with_reasoning(messages=[{"role": "user", "content": "hi"}])
    )

    assert content == "answer"
    assert reasoning == ""


def test_chat_thinking_enabled_empty_reasoning_no_log():
    p = _provider_with_client(thinking_enabled=True)
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content="answer", reasoning_content=None))]
        )
    )

    out = asyncio.run(p.chat(messages=[{"role": "user", "content": "hi"}]))

    assert out == "answer"


# ---------------------------------------------------------------------------
# DeepSeekProvider.chat_with_tools edge cases
# ---------------------------------------------------------------------------


def test_chat_with_tools_thinking_enabled_no_tool_calls():
    p = _provider_with_client(thinking_enabled=True)
    p.client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content="plain answer",
                        reasoning_content="",
                        tool_calls=None,
                    )
                )
            ]
        )
    )

    resp = asyncio.run(
        p.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
        )
    )

    assert resp.content == "plain answer"
    assert resp.tool_calls == []
    assert resp.reasoning_content is None
    kw = p.client.chat.completions.create.call_args.kwargs
    assert kw["tools"] == [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    assert "temperature" not in kw


# ---------------------------------------------------------------------------
# DeepSeekProvider.chat_stream
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, chunks, exit_error=None, close_error=None):
        self.chunks = list(chunks)
        self.index = 0
        self.exit_error = exit_error
        self.close_error = close_error
        self.closed = False
        self.exit_called = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk

    async def __aexit__(self, *args):
        self.exit_called += 1
        if self.exit_error:
            raise self.exit_error

    async def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def _run_stream(provider, stream):
    provider.client.chat.completions.create = AsyncMock(return_value=stream)

    async def _collect():
        return [
            chunk
            async for chunk in provider.chat_stream(messages=[{"role": "user", "content": "hi"}])
        ]

    return asyncio.run(_collect())


def test_chat_stream_yields_text_and_exits():
    p = _provider_with_client()
    stream = _FakeStream(
        [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]),
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))]),
        ]
    )

    tokens = _run_stream(p, stream)

    assert tokens == ["Hel", "lo"]
    assert stream.exit_called == 1
    assert stream.closed is False  # normal path uses __aexit__, not close()
    kw = p.client.chat.completions.create.call_args.kwargs
    assert kw["stream"] is True


def test_chat_stream_falls_back_to_close_when_aexit_raises():
    p = _provider_with_client()
    stream = _FakeStream(
        [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="x"))])],
        exit_error=RuntimeError("aexit failed"),
    )

    tokens = _run_stream(p, stream)

    assert tokens == ["x"]
    assert stream.exit_called == 1
    assert stream.closed is True


def test_chat_stream_swallows_close_error():
    p = _provider_with_client()
    stream = _FakeStream(
        [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="x"))])],
        exit_error=RuntimeError("aexit failed"),
        close_error=RuntimeError("close failed"),
    )

    tokens = _run_stream(p, stream)

    assert tokens == ["x"]
    assert stream.closed is True


# ---------------------------------------------------------------------------
# _call_with_retry wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_with_retry_timeout_none_no_wait_for():
    provider = MagicMock()
    provider.chat = AsyncMock(return_value="ok")
    result = await call_llm_with_retry(
        provider, messages=[{"role": "user", "content": "hi"}], timeout=None
    )
    assert result == "ok"
    assert provider.chat.await_count == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_bare_429_retries_then_succeeds():
    provider = MagicMock()
    provider.chat = AsyncMock(
        side_effect=[
            APIStatusError("429", response=MagicMock(status_code=429), body=None),
            "ok",
        ]
    )

    result = await call_llm_with_retry(
        provider,
        messages=[{"role": "user", "content": "hi"}],
        max_retries=2,
        base_delay=0,
    )

    assert result == "ok"
    assert provider.chat.await_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_retry_bare_429_exhausted_raises():
    provider = MagicMock()
    provider.chat = AsyncMock(
        side_effect=APIStatusError("429", response=MagicMock(status_code=429), body=None)
    )

    with pytest.raises(APIStatusError):
        await call_llm_with_retry(
            provider,
            messages=[{"role": "user", "content": "hi"}],
            max_retries=2,
            base_delay=0,
        )
    assert provider.chat.await_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_reasoning_retry_retries():
    provider = MagicMock()
    provider.chat_with_reasoning = AsyncMock(
        side_effect=[
            RateLimitError("slow down", response=MagicMock(), body=None),
            ("answer", "reason"),
        ]
    )

    result = await call_llm_with_reasoning_retry(
        provider,
        messages=[{"role": "user", "content": "hi"}],
        max_retries=2,
        base_delay=0,
    )

    assert result == ("answer", "reason")
    assert provider.chat_with_reasoning.await_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_tools_retry_success():
    provider = MagicMock()
    provider.chat_with_tools = AsyncMock(return_value=MagicMock(content="tool result"))

    resp = await call_llm_with_tools_retry(
        provider,
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
        tool_choice="required",
        temperature=0.2,
        max_tokens=128,
        max_retries=1,
        timeout=None,
    )

    assert resp.content == "tool result"
    kw = provider.chat_with_tools.await_args.kwargs
    assert kw["tools"] == [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    assert kw["tool_choice"] == "required"
    assert kw["temperature"] == 0.2
    assert kw["max_tokens"] == 128


@pytest.mark.asyncio
async def test_call_llm_with_tools_retry_retries_on_timeout():
    provider = MagicMock()
    provider.chat_with_tools = AsyncMock(
        side_effect=[
            APIStatusError("429", response=MagicMock(status_code=429), body=None),
            MagicMock(content="ok"),
        ]
    )

    resp = await call_llm_with_tools_retry(
        provider,
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        max_retries=2,
        base_delay=0,
        timeout=None,
    )

    assert resp.content == "ok"
    assert provider.chat_with_tools.await_count == 2


# ---------------------------------------------------------------------------
# create_provider
# ---------------------------------------------------------------------------


def test_create_provider_openai_branch_and_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    cfg = Config(
        llm=LLMConfig(
            provider="openai",
            model="gpt-test",
            base_url="http://openai.local",
            thinking=ThinkingConfig(enabled=True, effort="max"),
        )
    )

    p = create_provider(cfg, thinking_enabled=False, thinking_effort="low")

    assert isinstance(p, DeepSeekProvider)
    assert p.model == "gpt-test"
    assert p.thinking_enabled is False
    assert p.thinking_effort == "low"


def test_create_provider_uses_config_thinking_when_no_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cfg = Config(
        llm=LLMConfig(
            provider="deepseek",
            model="deepseek-test",
            thinking=ThinkingConfig(enabled=True, effort="max"),
        )
    )

    p = create_provider(cfg)

    assert isinstance(p, DeepSeekProvider)
    assert p.thinking_enabled is True
    assert p.thinking_effort == "max"


def test_call_with_retry_direct_uses_timeout_and_nonretryable_passthrough():
    """Direct _call_with_retry coverage for non-retryable API status errors."""

    async def run():
        calls = 0

        async def fail():
            nonlocal calls
            calls += 1
            raise APIStatusError("500", response=MagicMock(status_code=500), body=None)

        with pytest.raises(APIStatusError):
            await _call_with_retry(fail, max_retries=3, base_delay=0, timeout=None)
        return calls

    assert asyncio.run(run()) == 1
