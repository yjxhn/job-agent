"""LLM providers via openai SDK."""

import asyncio
import logging

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from .base import LLMProvider

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


class DeepSeekProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-pro",
    ):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None) -> str:
        kwargs = dict(
            model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        if response_format:
            kwargs["response_format"] = response_format
        resp = await self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


async def call_llm_with_retry(
    provider: LLMProvider,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict | None = None,
    max_retries: int = _MAX_RETRIES,
    base_delay: float = _BASE_DELAY,
) -> str:
    """Call provider.chat() with exponential backoff on rate-limit/timeout/connection errors.

    Retries up to `max_retries` times with delays of base_delay * 2^attempt seconds.
    """
    for attempt in range(max_retries):
        try:
            return await provider.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except _RETRYABLE_EXCEPTIONS as e:
            if attempt == max_retries - 1:
                logger.error(
                    f"LLM call failed after {max_retries} attempts: {type(e).__name__}: {e}"
                )
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                f"LLM {type(e).__name__} on attempt {attempt + 1}/{max_retries}, "
                f"retrying in {delay:.1f}s: {e}"
            )
            await asyncio.sleep(delay)
        except APIStatusError as e:
            if e.status_code == 429:
                if attempt == max_retries - 1:
                    logger.error(f"LLM call failed after {max_retries} attempts: 429: {e}")
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"LLM 429 on attempt {attempt + 1}/{max_retries}, " f"retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError("Unreachable: retry loop should have raised or returned")  # pragma: no cover


def create_provider(config) -> LLMProvider:
    p = config.llm.provider
    if p in ("deepseek", "openai"):
        return DeepSeekProvider(
            api_key=config.api_key, base_url=config.llm.base_url, model=config.llm.model
        )
    raise ValueError(f"Unsupported LLM provider: {p}")
