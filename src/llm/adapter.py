"""LLM adapter layer: unified data structures and abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.streaming.events import StreamEvent


@dataclass
class Usage:
    """Token consumption, normalized across all providers."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0


@dataclass
class ToolCallRequest:
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Usage = field(default_factory=Usage)
    thinking: str | None = None


class LLMAdapter(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Call the LLM and return a standardized response."""

    @abstractmethod
    def call_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]:
        """Stream the LLM response as unified StreamEvent objects."""
