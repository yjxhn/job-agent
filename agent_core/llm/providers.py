"""LLM providers via openai SDK."""

import logging

from openai import AsyncOpenAI

from .base import LLMProvider

logger = logging.getLogger(__name__)


class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-v4-pro"):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def chat(self, messages, temperature=0.7, max_tokens=4096,
                   response_format=None) -> str:
        kwargs = dict(model=self.model, messages=messages,
                      temperature=temperature, max_tokens=max_tokens)
        if response_format:
            kwargs["response_format"] = response_format
        resp = await self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


def create_provider(config) -> LLMProvider:
    p = config.llm.provider
    if p in ("deepseek", "openai"):
        return DeepSeekProvider(api_key=config.api_key,
                                base_url=config.llm.base_url,
                                model=config.llm.model)
    raise ValueError(f"Unsupported LLM provider: {p}")
