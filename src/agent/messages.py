"""Message format helpers for OpenAI-compatible dict construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.adapter import LLMResponse
    from src.tools.base import ToolResult


def format_assistant_msg(response: LLMResponse) -> dict:
    """Convert LLMResponse to OpenAI assistant message dict.

    - tool_calls arguments are stored as dict (not JSON string).
    - thinking is stored as a non-standard field for Phase 4 Anthropic.
    """
    msg: dict = {"role": "assistant"}

    if response.content is not None:
        msg["content"] = response.content

    if response.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for tc in response.tool_calls
        ]

    if response.thinking is not None:
        msg["thinking"] = response.thinking

    return msg


def format_tool_msg(tool_call_id: str, result: ToolResult) -> dict:
    """Convert a tool result to OpenAI tool message dict."""
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": result.output,
    }


def format_user_msg(text: str) -> dict:
    """Create an OpenAI user message dict."""
    return {"role": "user", "content": text}
