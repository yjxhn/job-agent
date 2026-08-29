"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """Represents a single tool call from the LLM."""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class ChatResponse:
    """Response from chat_with_tools, may contain text, tool calls, or both."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None  # DeepSeek thinking mode chain-of-thought


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str: ...

    async def chat_with_reasoning(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> tuple[str, str]:
        """Return (content, reasoning_content).

        reasoning_content is the model's chain-of-thought when thinking mode is
        enabled, empty string otherwise. Default falls back to chat() with no
        reasoning (backward compatible for providers that don't support thinking).
        """
        content = await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return content, ""

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Send messages with tool definitions. Default raises NotImplementedError."""
        raise NotImplementedError("chat_with_tools not implemented by this provider")

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream plain-text chat tokens. Default raises NotImplementedError."""
        raise NotImplementedError("chat_stream not implemented by this provider")
