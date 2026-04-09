"""OpenAI-compatible LLM adapter. Works with OpenAI, DeepSeek, Ollama, Gemini."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator  # noqa: TC003

import httpx

from src.llm.adapter import LLMAdapter, LLMResponse, ToolCallRequest, Usage
from src.streaming.events import StreamEvent

logger = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.0  # seconds


class LLMAPIError(Exception):
    """Raised when the LLM API returns a non-retryable error."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"LLM API error {status_code}: {body}")


class OpenAICompatAdapter(LLMAdapter):
    """Adapter for any OpenAI-compatible API."""

    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=self.api_base,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    async def call(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> LLMResponse:
        body: dict = {"model": self.model, "messages": messages, **kwargs}
        if tools:
            body["tools"] = tools

        # Try non-streaming first; fall back to streaming if server requires it
        data = await self._request(body)
        return self._parse_response(data)

    async def call_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]:
        body: dict = {"model": self.model, "messages": messages, "stream": True, **kwargs}
        if tools:
            body["tools"] = tools

        # tool_call accumulator: index -> {id, name, arg_chunks}
        tc_acc: dict[int, dict] = {}
        usage_acc: dict = {}
        finish_reason = "stop"

        last_error: Exception | None = None
        resp_ctx = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp_ctx = self._client.stream("POST", "/chat/completions", json=body)
                resp = await resp_ctx.__aenter__()

                if resp.status_code == 200:
                    break

                # Read error body before closing
                error_body = await resp.aread()
                await resp_ctx.__aexit__(None, None, None)
                resp_ctx = None

                if resp.status_code not in _RETRY_STATUS_CODES:
                    raise LLMAPIError(resp.status_code, error_body.decode())

                last_error = LLMAPIError(resp.status_code, error_body.decode())
                logger.warning("LLM API %d, retry %d/%d", resp.status_code, attempt + 1, _MAX_RETRIES)

            except httpx.HTTPError as exc:
                if resp_ctx:
                    with contextlib.suppress(Exception):
                        await resp_ctx.__aexit__(None, None, None)
                    resp_ctx = None
                last_error = exc
                logger.warning("LLM HTTP error: %s, retry %d/%d", exc, attempt + 1, _MAX_RETRIES)

            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2**attempt)
                await asyncio.sleep(delay)
        else:
            raise last_error  # type: ignore[misc]

        # Stream is open with status 200 — parse SSE
        try:
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break

                chunk = json.loads(payload)

                if chunk.get("usage"):
                    usage_acc = chunk["usage"]

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr

                # Text delta
                if delta.get("content"):
                    yield StreamEvent(type="text_delta", content=delta["content"])

                # Thinking delta
                if delta.get("reasoning_content"):
                    yield StreamEvent(type="thinking_delta", content=delta["reasoning_content"])

                # Tool call deltas
                for tc in delta.get("tool_calls") or []:
                    idx = tc["index"]
                    if idx not in tc_acc:
                        tc_acc[idx] = {"id": tc.get("id", ""), "name": "", "arg_chunks": []}
                    entry = tc_acc[idx]
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    func = tc.get("function", {})
                    if func.get("name"):
                        entry["name"] = func["name"]
                        yield StreamEvent(type="tool_start", tool_call_id=entry["id"], name=entry["name"])
                    if func.get("arguments"):
                        entry["arg_chunks"].append(func["arguments"])
                        yield StreamEvent(type="tool_delta", content=func["arguments"])

        except Exception as exc:
            yield StreamEvent(type="error", content=f"Stream error: {exc}")
            return
        finally:
            if resp_ctx:
                await resp_ctx.__aexit__(None, None, None)

        # Emit tool_end events for accumulated tool calls
        for idx in sorted(tc_acc.keys()):
            entry = tc_acc[idx]
            full_args = "".join(entry["arg_chunks"])
            try:
                args = json.loads(full_args) if full_args else {}
            except json.JSONDecodeError:
                args = {}
            yield StreamEvent(
                type="tool_end",
                tool_call=ToolCallRequest(id=entry["id"], name=entry["name"], arguments=args),
            )

        yield StreamEvent(
            type="usage",
            usage=Usage(
                input_tokens=usage_acc.get("prompt_tokens", 0),
                output_tokens=usage_acc.get("completion_tokens", 0),
                thinking_tokens=usage_acc.get("reasoning_tokens", 0),
            ),
        )
        yield StreamEvent(type="done", finish_reason=finish_reason)

    async def _request(self, body: dict) -> dict:
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._client.post("/chat/completions", json=body)

                if resp.status_code == 200:
                    return resp.json()

                # Some proxies require stream=true; detect and retry as stream
                if (
                    resp.status_code == 400
                    and "stream" in resp.text.lower()
                    and not body.get("stream")
                ):
                    logger.info("Server requires streaming, switching to stream mode")
                    body["stream"] = True
                    return await self._request_stream(body)

                if resp.status_code not in _RETRY_STATUS_CODES:
                    raise LLMAPIError(resp.status_code, resp.text)

                last_error = LLMAPIError(resp.status_code, resp.text)
                logger.warning(
                    "LLM API %d, retry %d/%d",
                    resp.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                )

            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "LLM HTTP error: %s, retry %d/%d",
                    exc,
                    attempt + 1,
                    _MAX_RETRIES,
                )

            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2**attempt)
                await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]

    async def _request_stream(self, body: dict) -> dict:
        """Consume an SSE stream and reassemble into a single response dict."""
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: dict[int, dict] = {}  # index -> {id, function: {name, arguments}}
        finish_reason = "stop"
        usage: dict = {}

        async with self._client.stream(
            "POST", "/chat/completions", json=body
        ) as resp:
            if resp.status_code != 200:
                text = await resp.aread()
                raise LLMAPIError(resp.status_code, text.decode())

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break

                chunk = json.loads(payload)

                # Usage may appear in the final chunk
                if "usage" in chunk and chunk["usage"]:
                    usage = chunk["usage"]

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr

                # Text content
                if delta.get("content"):
                    content_parts.append(delta["content"])

                # Thinking / reasoning
                if delta.get("reasoning_content"):
                    thinking_parts.append(delta["reasoning_content"])

                # Tool calls (streamed incrementally)
                for tc in (delta.get("tool_calls") or []):
                    idx = tc["index"]
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = tool_calls[idx]
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    func = tc.get("function", {})
                    if func.get("name"):
                        entry["function"]["name"] = func["name"]
                    if func.get("arguments"):
                        entry["function"]["arguments"] += func["arguments"]

        # Reassemble into standard non-streaming response format
        message: dict = {}
        if content_parts:
            message["content"] = "".join(content_parts)
        if thinking_parts:
            message["reasoning_content"] = "".join(thinking_parts)
        if tool_calls:
            message["tool_calls"] = [
                tool_calls[i] for i in sorted(tool_calls.keys())
            ]

        return {
            "choices": [
                {"message": message, "finish_reason": finish_reason}
            ],
            "usage": usage,
        }

    def _parse_response(self, data: dict) -> LLMResponse:
        choice = data["choices"][0]
        message = choice["message"]

        return LLMResponse(
            content=message.get("content"),
            tool_calls=self._parse_tool_calls(message.get("tool_calls")),
            finish_reason=choice.get("finish_reason", "stop"),
            usage=self._parse_usage(data.get("usage", {})),
            thinking=message.get("reasoning_content"),
        )

    def _parse_tool_calls(
        self, raw: list[dict] | None
    ) -> list[ToolCallRequest]:
        if not raw:
            return []

        result = []
        for tc in raw:
            func = tc["function"]
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                args = json.loads(args)
            result.append(
                ToolCallRequest(id=tc["id"], name=func["name"], arguments=args)
            )
        return result

    def _parse_usage(self, raw: dict) -> Usage:
        return Usage(
            input_tokens=raw.get("prompt_tokens", 0),
            output_tokens=raw.get("completion_tokens", 0),
            thinking_tokens=raw.get("reasoning_tokens", 0),
        )
