"""Unified streaming event type for all LLM providers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.adapter import ToolCallRequest, Usage

# Valid event types
EVENT_TYPES = frozenset({
    "text_delta",
    "thinking_delta",
    "tool_start",
    "tool_delta",
    "tool_end",
    "tool_result",
    "usage",
    "done",
    "error",
})


@dataclass
class StreamEvent:
    """A single streaming event, unified across OpenAI and Anthropic.

    Adapter layer translates provider-specific SSE deltas into StreamEvent.
    Agent loop consumes and re-yields these, adding tool_result events.
    """

    type: str
    content: str = ""
    tool_call_id: str = ""
    name: str = ""
    tool_call: ToolCallRequest | None = None
    output: str = ""
    success: bool = True
    usage: Usage | None = None
    finish_reason: str = ""

    def to_sse(self) -> str:
        """Serialize to SSE wire format: event: {type}\\ndata: {json}\\n\\n"""
        data: dict = {}

        if self.type in ("text_delta", "thinking_delta", "error"):
            data["content"] = self.content

        elif self.type == "tool_start":
            data["tool_call_id"] = self.tool_call_id
            data["name"] = self.name

        elif self.type == "tool_delta":
            data["content"] = self.content

        elif self.type == "tool_end":
            if self.tool_call:
                data["tool_call_id"] = self.tool_call.id
                data["name"] = self.tool_call.name
                data["arguments"] = self.tool_call.arguments

        elif self.type == "tool_result":
            data["tool_call_id"] = self.tool_call_id
            data["output"] = self.output
            data["success"] = self.success

        elif self.type == "usage":
            if self.usage:
                data["input_tokens"] = self.usage.input_tokens
                data["output_tokens"] = self.usage.output_tokens
                data["thinking_tokens"] = self.usage.thinking_tokens

        elif self.type == "done":
            data["finish_reason"] = self.finish_reason

        return f"event: {self.type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
