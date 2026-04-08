"""Anthropic Messages API adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from src.llm.adapter import LLMAdapter, LLMResponse, ToolCallRequest, Usage
from src.llm.openai_compat import LLMAPIError

logger = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.0


class AnthropicAdapter(LLMAdapter):
    """Adapter for the Anthropic Messages API."""

    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=self.api_base,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=120.0,
        )

    async def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        body = self._build_request(messages, tools, **kwargs)
        data = await self._request(body, kwargs)
        return self._parse_response(data)

    # ── Request construction ────────────────────────────────

    def _build_request(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> dict:
        system: str | None = None
        converted: list[dict] = []

        for msg in messages:
            role = msg.get("role")

            if role == "system":
                system = msg.get("content", "")
                continue

            if role == "assistant":
                blocks = self._convert_assistant(msg)
                converted.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                block = self._convert_tool_result(msg)
                converted.append({"role": "user", "content": [block]})
                continue

            if role == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    converted.append({"role": "user", "content": content})
                else:
                    converted.append({
                        "role": "user",
                        "content": self._convert_content_blocks(content),
                    })
                continue

        # Merge adjacent same-role messages
        merged = self._merge_adjacent(converted)

        body: dict = {"model": self.model, "messages": merged, "max_tokens": 4096}
        if system:
            body["system"] = system

        if tools:
            body["tools"] = self._convert_tools(tools)

        # Forward supported kwargs
        for key in ("max_tokens", "temperature", "top_p", "stop_sequences"):
            if key in kwargs:
                body[key] = kwargs[key]

        return body

    def _convert_assistant(self, msg: dict) -> list[dict]:
        """Convert an assistant message to Anthropic content blocks."""
        blocks: list[dict] = []

        content = msg.get("content")
        if content:
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                blocks.extend(self._convert_content_blocks(content))

        for tc in msg.get("tool_calls", []):
            func = tc.get("function", {})
            args = func.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": func["name"],
                "input": args,
            })

        return blocks if blocks else [{"type": "text", "text": ""}]

    def _convert_tool_result(self, msg: dict) -> dict:
        """Convert a tool result message to Anthropic tool_result block."""
        return {
            "type": "tool_result",
            "tool_use_id": msg["tool_call_id"],
            "content": msg.get("content", ""),
        }

    def _convert_content_blocks(self, blocks: list[dict]) -> list[dict]:
        """Convert OpenAI-style content blocks to Anthropic format."""
        result: list[dict] = []
        for block in blocks:
            btype = block.get("type")
            if btype == "text":
                result.append({"type": "text", "text": block.get("text", "")})
            elif btype == "image_url":
                result.append(self._convert_image_url(block))
            else:
                result.append(block)
        return result

    def _convert_image_url(self, block: dict) -> dict:
        """Convert OpenAI image_url block to Anthropic image block."""
        url = block.get("image_url", {}).get("url", "")
        media_type, data = self._parse_data_uri(url)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": data,
            },
        }

    @staticmethod
    def _parse_data_uri(uri: str) -> tuple[str, str]:
        """Extract media_type and base64 data from a data URI."""
        match = re.match(r"data:([^;]+);base64,(.+)", uri, re.DOTALL)
        if match:
            return match.group(1), match.group(2)
        return "image/png", uri

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert OpenAI tool definitions to Anthropic format."""
        result: list[dict] = []
        for tool in tools:
            func = tool.get("function", tool)
            result.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    @staticmethod
    def _merge_adjacent(messages: list[dict]) -> list[dict]:
        """Merge adjacent messages with the same role (Anthropic requires alternating)."""
        if not messages:
            return messages

        merged: list[dict] = []
        for msg in messages:
            if merged and merged[-1]["role"] == msg["role"]:
                prev = merged[-1]
                prev_content = prev["content"]
                curr_content = msg["content"]

                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]

                prev["content"] = prev_content + curr_content
            else:
                merged.append(msg.copy())

        return merged

    # ── Response parsing ────────────────────────────────────

    def _parse_response(self, data: dict) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        thinking_parts: list[str] = []

        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "text":
                content_parts.append(block["text"])
            elif btype == "tool_use":
                tool_calls.append(ToolCallRequest(
                    id=block["id"],
                    name=block["name"],
                    arguments=block.get("input", {}),
                ))
            elif btype == "thinking":
                thinking_parts.append(block.get("thinking", ""))

        # Stop reason mapping
        stop_reason = data.get("stop_reason", "end_turn")
        finish_reason = "tool_calls" if stop_reason == "tool_use" else "stop"

        # Usage
        usage_data = data.get("usage", {})
        usage = Usage(
            input_tokens=usage_data.get("input_tokens", 0),
            output_tokens=usage_data.get("output_tokens", 0),
            thinking_tokens=usage_data.get("cache_read_input_tokens", 0),
        )

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            thinking="\n".join(thinking_parts) if thinking_parts else None,
        )

    # ── HTTP with retry ─────────────────────────────────────

    async def _request(self, body: dict, kwargs: dict | None = None) -> dict:
        headers: dict[str, str] = {}
        if kwargs and "thinking" in kwargs:
            body["thinking"] = kwargs["thinking"]
            headers["anthropic-beta"] = "interleaved-thinking-2025-05-14"

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._client.post(
                    "/v1/messages",
                    json=body,
                    headers=headers if headers else None,
                )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code not in _RETRY_STATUS_CODES:
                    raise LLMAPIError(resp.status_code, resp.text)

                last_error = LLMAPIError(resp.status_code, resp.text)
                logger.warning(
                    "Anthropic API %d, retry %d/%d",
                    resp.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )

            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Anthropic HTTP error: %s, retry %d/%d",
                    exc,
                    attempt + 1,
                    _MAX_RETRIES,
                )

            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2**attempt)
                await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]
