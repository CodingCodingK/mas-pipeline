"""Unit tests for StreamEvent + adapter call_stream (mock-based).

Tests 7.1 through 7.10 from the streaming tasks.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.adapter import ToolCallRequest, Usage
from src.streaming.events import EVENT_TYPES, StreamEvent

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


# ── 7.1 StreamEvent construction ────────────────────────────


def test_stream_event_construction():
    print("\n=== 7.1 StreamEvent construction ===")

    for etype in EVENT_TYPES:
        ev = StreamEvent(type=etype)
        check(f"{etype} default content", ev.content == "")
        check(f"{etype} default tool_call", ev.tool_call is None)

    ev = StreamEvent(type="text_delta", content="hello")
    check("text_delta content", ev.content == "hello")

    tc = ToolCallRequest(id="x", name="read_file", arguments={"path": "/a"})
    ev = StreamEvent(type="tool_end", tool_call=tc)
    check("tool_end tool_call", ev.tool_call is not None and ev.tool_call.name == "read_file")

    ev = StreamEvent(type="done", finish_reason="stop")
    check("done finish_reason", ev.finish_reason == "stop")

    ev = StreamEvent(type="usage", usage=Usage(10, 20, 5))
    check("usage field", ev.usage is not None and ev.usage.input_tokens == 10)


# ── 7.2 StreamEvent.to_sse() ────────────────────────────────


def test_to_sse():
    print("\n=== 7.2 StreamEvent.to_sse() ===")

    ev = StreamEvent(type="text_delta", content="你好")
    sse = ev.to_sse()
    check("text_delta SSE format", sse.startswith("event: text_delta\n"))
    check("text_delta data JSON", '"content": "你好"' in sse)
    check("SSE ends with double newline", sse.endswith("\n\n"))

    ev = StreamEvent(type="tool_start", tool_call_id="call_1", name="shell")
    sse = ev.to_sse()
    data = json.loads(sse.split("data: ")[1].strip())
    check("tool_start tool_call_id", data["tool_call_id"] == "call_1")
    check("tool_start name", data["name"] == "shell")

    tc = ToolCallRequest(id="c1", name="read_file", arguments={"path": "/a"})
    ev = StreamEvent(type="tool_end", tool_call=tc)
    sse = ev.to_sse()
    data = json.loads(sse.split("data: ")[1].strip())
    check("tool_end arguments", data["arguments"] == {"path": "/a"})

    ev = StreamEvent(type="tool_result", tool_call_id="c1", output="content here", success=True)
    sse = ev.to_sse()
    data = json.loads(sse.split("data: ")[1].strip())
    check("tool_result output", data["output"] == "content here")
    check("tool_result success", data["success"] is True)

    ev = StreamEvent(type="usage", usage=Usage(100, 50, 10))
    sse = ev.to_sse()
    data = json.loads(sse.split("data: ")[1].strip())
    check("usage input_tokens", data["input_tokens"] == 100)
    check("usage thinking_tokens", data["thinking_tokens"] == 10)

    ev = StreamEvent(type="done", finish_reason="completed")
    sse = ev.to_sse()
    data = json.loads(sse.split("data: ")[1].strip())
    check("done finish_reason", data["finish_reason"] == "completed")

    ev = StreamEvent(type="error", content="something broke")
    sse = ev.to_sse()
    data = json.loads(sse.split("data: ")[1].strip())
    check("error content", data["content"] == "something broke")


# ── 7.3-7.5 OpenAI call_stream mock tests ───────────────────


class FakeSSEResponse:
    """Simulate httpx streaming response with SSE lines."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b"error body"


class FakeStreamContext:
    """Simulate httpx stream context manager."""

    def __init__(self, resp: FakeSSEResponse):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *args):
        pass


def test_openai_call_stream():
    print("\n=== 7.3 OpenAI call_stream mock test ===")

    from src.llm.openai_compat import OpenAICompatAdapter

    adapter = OpenAICompatAdapter(api_base="http://fake", api_key="key", model="gpt-4")

    # Text-only response
    sse_lines = [
        'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
        "data: [DONE]",
    ]

    resp = FakeSSEResponse(sse_lines)
    ctx = FakeStreamContext(resp)

    events: list[StreamEvent] = []

    async def run():
        with patch.object(adapter._client, "stream", return_value=ctx):
            async for ev in adapter.call_stream([{"role": "user", "content": "hi"}]):
                events.append(ev)

    asyncio.run(run())

    types = [e.type for e in events]
    check("has text_delta events", types.count("text_delta") == 2)
    check("has usage event", "usage" in types)
    check("has done event", "done" in types)
    check("first text_delta content", events[0].content == "Hello")
    check("done finish_reason", [e for e in events if e.type == "done"][0].finish_reason == "stop")

    usage_ev = [e for e in events if e.type == "usage"][0]
    check("usage input_tokens", usage_ev.usage.input_tokens == 10)


def test_openai_call_stream_multi_tool():
    print("\n=== 7.4 OpenAI multi tool_call test ===")

    from src.llm.openai_compat import OpenAICompatAdapter

    adapter = OpenAICompatAdapter(api_base="http://fake", api_key="key", model="gpt-4")

    sse_lines = [
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read_file","arguments":""}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"path\\""}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\\"/a\\"}"}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"id":"c2","function":{"name":"shell","arguments":""}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"arguments":"{\\"cmd\\":\\"ls\\"}"}}]},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]

    resp = FakeSSEResponse(sse_lines)
    ctx = FakeStreamContext(resp)
    events: list[StreamEvent] = []

    async def run():
        with patch.object(adapter._client, "stream", return_value=ctx):
            async for ev in adapter.call_stream([{"role": "user", "content": "do stuff"}]):
                events.append(ev)

    asyncio.run(run())

    tool_starts = [e for e in events if e.type == "tool_start"]
    tool_ends = [e for e in events if e.type == "tool_end"]
    check("two tool_start events", len(tool_starts) == 2)
    check("two tool_end events", len(tool_ends) == 2)
    check("first tool is read_file", tool_ends[0].tool_call.name == "read_file")
    check("second tool is shell", tool_ends[1].tool_call.name == "shell")
    check("read_file args parsed", tool_ends[0].tool_call.arguments == {"path": "/a"})
    check("shell args parsed", tool_ends[1].tool_call.arguments == {"cmd": "ls"})


def test_openai_empty_content_skip():
    print("\n=== 7.5 OpenAI empty content skip test ===")

    from src.llm.openai_compat import OpenAICompatAdapter

    adapter = OpenAICompatAdapter(api_base="http://fake", api_key="key", model="gpt-4")

    sse_lines = [
        'data: {"choices":[{"delta":{"content":""},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":"real text"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]

    resp = FakeSSEResponse(sse_lines)
    ctx = FakeStreamContext(resp)
    events: list[StreamEvent] = []

    async def run():
        with patch.object(adapter._client, "stream", return_value=ctx):
            async for ev in adapter.call_stream([{"role": "user", "content": "hi"}]):
                events.append(ev)

    asyncio.run(run())

    text_deltas = [e for e in events if e.type == "text_delta"]
    check("only one text_delta (empty skipped)", len(text_deltas) == 1)
    check("text_delta has real content", text_deltas[0].content == "real text")


# ── 7.6-7.8 Anthropic call_stream mock tests ────────────────


def test_anthropic_call_stream():
    print("\n=== 7.6 Anthropic call_stream mock test ===")

    from src.llm.anthropic import AnthropicAdapter

    adapter = AnthropicAdapter(api_base="http://fake", api_key="key", model="claude-3")

    sse_lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":15}}}',
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}',
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "event: message_delta",
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":8}}',
        "event: message_stop",
        'data: {"type":"message_stop"}',
    ]

    resp = FakeSSEResponse(sse_lines)
    ctx = FakeStreamContext(resp)
    events: list[StreamEvent] = []

    async def run():
        # Patch _build_request to return a simple body
        with patch.object(adapter, "_build_request", return_value={"model": "claude-3", "messages": [], "max_tokens": 4096}):
            with patch.object(adapter._client, "stream", return_value=ctx):
                async for ev in adapter.call_stream([{"role": "user", "content": "hi"}]):
                    events.append(ev)

    asyncio.run(run())

    types = [e.type for e in events]
    check("has text_delta events", types.count("text_delta") == 2)
    check("first text is Hello", events[0].content == "Hello")
    check("has usage", "usage" in types)
    check("has done", "done" in types)

    usage_ev = [e for e in events if e.type == "usage"][0]
    check("input_tokens=15", usage_ev.usage.input_tokens == 15)
    check("output_tokens=8", usage_ev.usage.output_tokens == 8)


def test_anthropic_thinking():
    print("\n=== 7.7 Anthropic thinking block test ===")

    from src.llm.anthropic import AnthropicAdapter

    adapter = AnthropicAdapter(api_base="http://fake", api_key="key", model="claude-3")

    sse_lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":5}}}',
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Let me think"}}',
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "event: content_block_start",
        'data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Answer"}}',
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":1}',
        "event: message_delta",
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}',
        "event: message_stop",
        'data: {"type":"message_stop"}',
    ]

    resp = FakeSSEResponse(sse_lines)
    ctx = FakeStreamContext(resp)
    events: list[StreamEvent] = []
    captured_body: dict = {}

    def fake_stream(method, url, json=None, headers=None):
        if json:
            captured_body.update(json)
        return ctx

    async def run():
        with patch.object(adapter, "_build_request", return_value={"model": "claude-3", "messages": [], "max_tokens": 4096}):
            with patch.object(adapter._client, "stream", side_effect=fake_stream):
                async for ev in adapter.call_stream(
                    [{"role": "user", "content": "hi"}],
                    thinking={"type": "enabled", "budget_tokens": 1024},
                ):
                    events.append(ev)

    asyncio.run(run())

    types = [e.type for e in events]
    check("has thinking_delta", "thinking_delta" in types)
    check("thinking content correct", [e for e in events if e.type == "thinking_delta"][0].content == "Let me think")
    check("has text_delta", "text_delta" in types)


def test_anthropic_stop_reason_mapping():
    print("\n=== 7.8 Anthropic stop_reason mapping test ===")

    from src.llm.anthropic import AnthropicAdapter

    adapter = AnthropicAdapter(api_base="http://fake", api_key="key", model="claude-3")

    # Test tool_use stop_reason
    sse_lines = [
        "event: message_start",
        'data: {"type":"message_start","message":{"usage":{"input_tokens":5}}}',
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"t1","name":"read_file"}}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"/a\\"}"}}',
        "event: content_block_stop",
        'data: {"type":"content_block_stop","index":0}',
        "event: message_delta",
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":10}}',
        "event: message_stop",
        'data: {"type":"message_stop"}',
    ]

    resp = FakeSSEResponse(sse_lines)
    ctx = FakeStreamContext(resp)
    events: list[StreamEvent] = []

    async def run():
        with patch.object(adapter, "_build_request", return_value={"model": "claude-3", "messages": [], "max_tokens": 4096}):
            with patch.object(adapter._client, "stream", return_value=ctx):
                async for ev in adapter.call_stream([{"role": "user", "content": "hi"}]):
                    events.append(ev)

    asyncio.run(run())

    done_ev = [e for e in events if e.type == "done"][0]
    check("tool_use -> tool_calls", done_ev.finish_reason == "tool_calls")

    tool_end = [e for e in events if e.type == "tool_end"][0]
    check("tool_end parsed args", tool_end.tool_call.arguments == {"path": "/a"})


# ── 7.9-7.10 Retry and mid-stream error tests ───────────────


def test_call_stream_retry():
    print("\n=== 7.9 call_stream retry test ===")

    from src.llm.openai_compat import OpenAICompatAdapter

    adapter = OpenAICompatAdapter(api_base="http://fake", api_key="key", model="gpt-4")

    call_count = 0

    class FailThenSuccessCtx:
        def __init__(self):
            pass

        async def __aenter__(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeSSEResponse([], status_code=429)
            return FakeSSEResponse([
                'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
                "data: [DONE]",
            ])

        async def __aexit__(self, *args):
            pass

    events: list[StreamEvent] = []

    async def run():
        with patch.object(adapter._client, "stream", return_value=FailThenSuccessCtx()):
            with patch("src.llm.openai_compat.asyncio.sleep", new_callable=AsyncMock):
                async for ev in adapter.call_stream([{"role": "user", "content": "hi"}]):
                    events.append(ev)

    asyncio.run(run())

    check("retried and got events", len(events) > 0)
    check("has text_delta after retry", any(e.type == "text_delta" for e in events))


def test_call_stream_mid_stream_error():
    print("\n=== 7.10 call_stream mid-stream error test ===")

    from src.llm.openai_compat import OpenAICompatAdapter

    adapter = OpenAICompatAdapter(api_base="http://fake", api_key="key", model="gpt-4")

    class ErrorResp:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}'
            raise ConnectionError("stream disconnected")

        async def aread(self):
            return b""

    class ErrorCtx:
        async def __aenter__(self):
            return ErrorResp()

        async def __aexit__(self, *args):
            pass

    events: list[StreamEvent] = []

    async def run():
        with patch.object(adapter._client, "stream", return_value=ErrorCtx()):
            async for ev in adapter.call_stream([{"role": "user", "content": "hi"}]):
                events.append(ev)

    asyncio.run(run())

    types = [e.type for e in events]
    check("got text_delta before error", "text_delta" in types)
    check("got error event", "error" in types)
    check("error content has info", "disconnected" in [e for e in events if e.type == "error"][0].content)


# ── Run all ──────────────────────────────────────────────────


if __name__ == "__main__":
    test_stream_event_construction()
    test_to_sse()
    test_openai_call_stream()
    test_openai_call_stream_multi_tool()
    test_openai_empty_content_skip()
    test_anthropic_call_stream()
    test_anthropic_thinking()
    test_anthropic_stop_reason_mapping()
    test_call_stream_retry()
    test_call_stream_mid_stream_error()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
