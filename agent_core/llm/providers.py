"""LLM providers via openai SDK."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from .base import ChatResponse, LLMProvider, ToolCall

logger = logging.getLogger(__name__)


def _clean_surrogates(text: str) -> str:
    """Replace lone surrogate characters (U+DC80–U+DCFF) that break UTF-8 encoding.

    DeepSeek's reasoning_content sometimes contains invalid surrogate pairs
    that are valid Python str but illegal in any Unicode encoding.  Round-trip
    through UTF-8 with ``surrogateescape`` so the bytes survive, then decode
    with ``replace`` to swap the offending bytes for U+FFFD.
    """
    if not text:
        return text
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")


async def _sanitize_response(response: httpx.Response) -> None:
    """httpx event hook: clean surrogate chars from JSON response bodies.

    DeepSeek's reasoning_content sometimes contains lone surrogates that
    break UTF-8 encoding when the OpenAI SDK processes the response.
    This hook runs BEFORE pydantic parsing, replacing surrogates with U+FFFD.
    """
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return
    try:
        body = await response.aread()
        text = body.decode("utf-8", errors="surrogateescape")
        text = _clean_surrogates(text)
        response._content = text.encode("utf-8")
    except Exception:
        pass  # best-effort; don't break the request on cleanup failure


_RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds
# 2026-08-17: 用户反馈“生成求职材料”等页面卡十几分钟。OpenAI SDK 默认超时很长，
# 且 call_llm_with_retry 本身无总超时，LLM 偶发不返回时前端会无限等待。
# 给所有 LLM 调用加一个总超时（含重试），超时后由调用方按失败处理。
LLM_CALL_TIMEOUT_SECONDS = 300.0


class DeepSeekProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        thinking_enabled: bool = False,
        thinking_effort: str = "high",
    ):
        self.model = model
        # trust_env=False so httpx ignores env vars (HTTP_PROXY/HTTPS_PROXY)
        # and Windows registry proxy settings. DeepSeek (api.deepseek.com)
        # is a domestic endpoint that must never go through a proxy/VPN.
        http_client = httpx.AsyncClient(
            trust_env=False,
            event_hooks={"response": [_sanitize_response]},
            # 2026-08-17: 显式连接/读超时 + 禁用 keep-alive，避免共享连接池里的
            # 半开连接让下一次 LLM 调用长时间无响应（用户侧表现为“卡住”）。
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=0),
        )
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,  # type: ignore[arg-type]  # openai SDK httpx2/httpx stub drift
        )
        self.thinking_enabled = thinking_enabled
        self.thinking_effort = thinking_effort

    def _thinking_kwargs(self) -> dict[str, Any]:
        """Return extra kwargs for thinking mode, or empty dict when disabled.

        When thinking is enabled:
        - reasoning_effort controls depth (high/max)
        - extra_body={"thinking":{"type":"enabled"}} toggles CoT
        - temperature/top_p are NOT included (API ignores them in thinking mode)

        Backward compatible: returns {} when thinking_enabled=False.
        """
        if not self.thinking_enabled:
            return {}
        return {
            "reasoning_effort": self.thinking_effort,
            "extra_body": {"thinking": {"type": "enabled"}},
        }

    async def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None) -> str:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format
        # Temperature only when NOT in thinking mode (API ignores it otherwise)
        if self.thinking_enabled:
            kwargs.update(self._thinking_kwargs())
        else:
            kwargs["temperature"] = temperature
        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        if self.thinking_enabled:
            rc = _clean_surrogates(getattr(msg, "reasoning_content", None) or "")
            if rc:
                logger.debug(f"DeepSeek reasoning_content: {len(rc)} chars")
        return _clean_surrogates(msg.content or "")

    async def chat_with_reasoning(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> tuple[str, str]:
        """chat() variant that returns (content, reasoning_content).

        Used by the precision-match pipeline so each match score has an
        auditable chain-of-thought stored alongside it. When thinking is
        disabled, reasoning_content is "" (empty string).
        """
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        if response_format:
            kwargs["response_format"] = response_format
        if self.thinking_enabled:
            kwargs.update(self._thinking_kwargs())
        else:
            kwargs["temperature"] = temperature
        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        content = _clean_surrogates(msg.content or "")
        reasoning = ""
        if self.thinking_enabled:
            rc = _clean_surrogates(getattr(msg, "reasoning_content", None) or "")
            if rc:
                reasoning = rc
                logger.debug(f"DeepSeek reasoning_content: {len(rc)} chars")
        return content, reasoning

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        if self.thinking_enabled:
            kwargs.update(self._thinking_kwargs())
        else:
            kwargs["temperature"] = temperature
        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        content = _clean_surrogates(msg.content or "")
        reasoning_content: str | None = None
        if self.thinking_enabled:
            rc = _clean_surrogates(getattr(msg, "reasoning_content", None) or "")
            reasoning_content = rc if rc else None
            if reasoning_content:
                logger.debug(f"DeepSeek reasoning_content: {len(reasoning_content)} chars")
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=_clean_surrogates(tc.function.arguments),
                    )
                )
        return ChatResponse(
            content=content if content else None,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """Stream plain-text chat tokens (no tool calls).

        Yields text delta strings as they arrive from the model. The final
        concatenated text equals what a non-streaming call would return.

        Implemented as an async generator with an explicit `finally` so the
        underlying OpenAI stream is closed even if the caller breaks out
        early or the loop raises — this prevents the "Task was destroyed
        but it is pending" warning that otherwise leaves an abandoned
        httpx response task holding the SSE socket open.
        """
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
        )
        if self.thinking_enabled:
            kwargs.update(self._thinking_kwargs())
        else:
            kwargs["temperature"] = temperature
        stream_ctx = await self.client.chat.completions.create(**kwargs)
        try:
            async for chunk in stream_ctx:
                try:
                    delta = chunk.choices[0].delta.content
                except (AttributeError, IndexError):
                    delta = None
                if delta:
                    yield _clean_surrogates(delta)
        finally:
            # The openai SDK's stream object is an AsyncContextManager; use
            # __aexit__ to release the httpx response (closes the conn).
            try:
                await stream_ctx.__aexit__(None, None, None)
            except Exception:
                # Fall back to a plain close() if __aexit__ isn't usable.
                close = getattr(stream_ctx, "close", None)
                if close is not None:
                    try:
                        await close()
                    except Exception:
                        pass


async def _call_with_retry(
    call,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
    label: str = "LLM",
    timeout: float | None = LLM_CALL_TIMEOUT_SECONDS,
):
    """Run ``call`` with exponential backoff on retryable errors.

    Shared retry loop behind the call_llm_with_*_retry wrappers. Retries
    rate-limit/timeout/connection errors — including a bare APIStatusError
    429, which non-openai-SDK callers can raise outside RateLimitError — up
    to ``max_retries`` times with delays of ``base_delay * 2**attempt``.

    ``timeout`` bounds the WHOLE retry loop (including backoff sleeps), so a
    hung upstream request cannot leave the dashboard stuck indefinitely.
    """

    async def _run():
        for attempt in range(max_retries):
            try:
                return await call()
            except _RETRYABLE_EXCEPTIONS as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"{label} call failed after {max_retries} attempts: "
                        f"{type(e).__name__}: {e}"
                    )
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"{label} {type(e).__name__} on attempt {attempt + 1}/{max_retries}, "
                    f"retrying in {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)
            except APIStatusError as e:
                if e.status_code == 429:
                    if attempt == max_retries - 1:
                        logger.error(f"{label} call failed after {max_retries} attempts: 429: {e}")
                        raise
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"{label} 429 on attempt {attempt + 1}/{max_retries}, "
                        f"retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        raise RuntimeError(
            "Unreachable: retry loop should have raised or returned"
        )  # pragma: no cover

    if timeout is None:
        return await _run()
    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except TimeoutError:
        logger.error(f"{label} call timed out after {timeout:.1f}s")
        raise


async def call_llm_with_retry(
    provider: LLMProvider,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict | None = None,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
    timeout: float | None = LLM_CALL_TIMEOUT_SECONDS,
) -> str:
    """Call provider.chat() with exponential backoff on rate-limit/timeout/connection errors.

    Retries up to `max_retries` times with delays of base_delay * 2^attempt seconds.
    ``timeout`` bounds the whole retry loop; default ``LLM_CALL_TIMEOUT_SECONDS``.
    """
    return await _call_with_retry(
        lambda: provider.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        ),
        max_retries=max_retries,
        base_delay=base_delay,
        timeout=timeout,
    )


async def call_llm_with_reasoning_retry(
    provider: LLMProvider,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict | None = None,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
    timeout: float | None = LLM_CALL_TIMEOUT_SECONDS,
) -> tuple[str, str]:
    """Call provider.chat_with_reasoning() with backoff. Returns (content, reasoning).

    Same retry logic as call_llm_with_retry, but preserves the reasoning_content
    (chain-of-thought) alongside the response text. Used by precision-match so
    each score has an auditable reasoning trail stored in match_results.reasoning.
    """
    return await _call_with_retry(
        lambda: provider.chat_with_reasoning(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        ),
        max_retries=max_retries,
        base_delay=base_delay,
        timeout=timeout,
    )


async def call_llm_with_tools_retry(
    provider: LLMProvider,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
    timeout: float | None = LLM_CALL_TIMEOUT_SECONDS,
) -> ChatResponse:
    """Call provider.chat_with_tools() with exponential backoff on retryable errors.

    ``timeout`` bounds the whole retry loop; default ``LLM_CALL_TIMEOUT_SECONDS``.
    """
    return await _call_with_retry(
        lambda: provider.chat_with_tools(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        max_retries=max_retries,
        base_delay=base_delay,
        label="LLM tools",
        timeout=timeout,
    )


def create_provider(
    config, thinking_enabled: bool | None = None, thinking_effort: str | None = None
) -> LLMProvider:
    p = config.llm.provider
    if p in ("deepseek", "openai"):
        thinking = getattr(config.llm, "thinking", None)
        enabled = thinking.enabled if thinking else False
        if thinking_enabled is not None:
            enabled = thinking_enabled
        effort = thinking.effort if thinking else "high"
        if thinking_effort is not None:
            effort = thinking_effort
        return DeepSeekProvider(
            api_key=config.api_key,
            base_url=config.llm.base_url,
            model=config.llm.model,
            thinking_enabled=enabled,
            thinking_effort=effort,
        )
    raise ValueError(f"Unsupported LLM provider: {p}")
