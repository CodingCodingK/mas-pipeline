"""Integration tests for agent_loop as AsyncGenerator.

Tests 8.1 through 8.8 from the streaming tasks.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.state import AgentState, ExitReason
from src.llm.adapter import LLMResponse, ToolCallRequest, Usage
from src.streaming.events import StreamEvent
from src.tools.base import ToolContext, ToolResult
from src.tools.orchestrator import ToolOrchestrator
from src.tools.registry import ToolRegistry

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


def make_state(
    adapter_events: list[list[StreamEvent]] | None = None,
    tools: dict | None = None,
    max_turns: int = 50,
    abort: bool = False,
) -> AgentState:
    """Create a test AgentState with mocked adapter and tools."""
    # Mock adapter
    adapter = MagicMock()
    adapter.model = "test-model"
    call_count = 0

    if adapter_events is None:
        adapter_events = [[
            StreamEvent(type="text_delta", content="Hello"),
            StreamEvent(type="usage", usage=Usage(10, 5, 0)),
            StreamEvent(type="done", finish_reason="stop"),
        ]]

    async def fake_call_stream(messages, tool_defs, **kwargs):
        nonlocal call_count
        events = adapter_events[min(call_count, len(adapter_events) - 1)]
        call_count += 1
        for ev in events:
            yield ev

    adapter.call_stream = fake_call_stream

    # Also mock call() for compact
    adapter.call = AsyncMock(return_value=LLMResponse(content="compact summary", usage=Usage(5, 5, 0)))

    # Mock tool registry
    registry = ToolRegistry()
    if tools:
        for name, func in tools.items():
            tool = MagicMock()
            tool.name = name
            registry.register(tool)

    # Mock orchestrator
    orchestrator = MagicMock(spec=ToolOrchestrator)
    orchestrator.dispatch = AsyncMock(return_value=[])

    # Tool context
    abort_signal = asyncio.Event() if abort else None
    if abort:
        abort_signal.set()

    tool_context = ToolContext(
        agent_id="test-agent",
        run_id="test-run",
        project_id=1,
        abort_signal=abort_signal,
    )

    return AgentState(
        messages=[
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": "Hello"},
        ],
        tools=registry,
        adapter=adapter,
        orchestrator=orchestrator,
        tool_context=tool_context,
        max_turns=max_turns,
    )


# ── 8.1 Single-turn text test ───────────────────────────────


def test_single_turn_text():
    print("\n=== 8.1 agent_loop single-turn text test ===")

    from src.agent.loop import agent_loop

    state = make_state()
    events: list[StreamEvent] = []

    async def run():
        async for ev in agent_loop(state):
            events.append(ev)

    asyncio.run(run())

    types = [e.type for e in events]
    check("has text_delta", "text_delta" in types)
    check("text content correct", events[0].content == "Hello")
    check("exit_reason COMPLETED", state.exit_reason == ExitReason.COMPLETED)
    check("assistant message in history", state.messages[-1]["role"] == "assistant")
    check("assistant content accumulated", state.messages[-1]["content"] == "Hello")


# ── 8.2 Multi-turn tool test ────────────────────────────────


def test_multi_turn_tool():
    print("\n=== 8.2 agent_loop multi-turn tool test ===")

    from src.agent.loop import agent_loop

    tc = ToolCallRequest(id="c1", name="read_file", arguments={"path": "/a"})

    # Turn 1: tool call
    turn1_events = [
        StreamEvent(type="tool_start", tool_call_id="c1", name="read_file"),
        StreamEvent(type="tool_delta", content='{"path":"/a"}'),
        StreamEvent(type="tool_end", tool_call=tc),
        StreamEvent(type="usage", usage=Usage(10, 5, 0)),
        StreamEvent(type="done", finish_reason="tool_calls"),
    ]

    # Turn 2: text response
    turn2_events = [
        StreamEvent(type="text_delta", content="File content is X"),
        StreamEvent(type="usage", usage=Usage(15, 10, 0)),
        StreamEvent(type="done", finish_reason="stop"),
    ]

    state = make_state(adapter_events=[turn1_events, turn2_events])
    state.orchestrator.dispatch = AsyncMock(return_value=[
        ToolResult(output="file content here", success=True),
    ])

    events: list[StreamEvent] = []

    async def run():
        async for ev in agent_loop(state):
            events.append(ev)

    asyncio.run(run())

    types = [e.type for e in events]
    check("has tool_start", "tool_start" in types)
    check("has tool_result", "tool_result" in types)
    check("has text_delta", "text_delta" in types)
    check("exit_reason COMPLETED", state.exit_reason == ExitReason.COMPLETED)

    tool_result_ev = [e for e in events if e.type == "tool_result"][0]
    check("tool_result output", tool_result_ev.output == "file content here")
    check("tool_result success", tool_result_ev.success is True)


# ── 8.3 Message accumulation test ───────────────────────────


def test_message_accumulation():
    print("\n=== 8.3 agent_loop message accumulation test ===")

    from src.agent.loop import agent_loop

    tc = ToolCallRequest(id="c1", name="shell", arguments={"cmd": "ls"})

    turn1_events = [
        StreamEvent(type="text_delta", content="Let me check"),
        StreamEvent(type="tool_start", tool_call_id="c1", name="shell"),
        StreamEvent(type="tool_end", tool_call=tc),
        StreamEvent(type="usage", usage=Usage(10, 5, 0)),
        StreamEvent(type="done", finish_reason="tool_calls"),
    ]

    turn2_events = [
        StreamEvent(type="text_delta", content="Done"),
        StreamEvent(type="usage", usage=Usage(10, 5, 0)),
        StreamEvent(type="done", finish_reason="stop"),
    ]

    state = make_state(adapter_events=[turn1_events, turn2_events])
    state.orchestrator.dispatch = AsyncMock(return_value=[
        ToolResult(output="file1.txt", success=True),
    ])

    async def run():
        async for _ in agent_loop(state):
            pass

    asyncio.run(run())

    # Check turn 1 assistant message (should have both content and tool_calls)
    assistant_msgs = [m for m in state.messages if m.get("role") == "assistant"]
    check("two assistant messages", len(assistant_msgs) == 2)
    check("first has content", assistant_msgs[0].get("content") == "Let me check")
    check("first has tool_calls", "tool_calls" in assistant_msgs[0])
    check("second has content", assistant_msgs[1].get("content") == "Done")

    # Check tool result message
    tool_msgs = [m for m in state.messages if m.get("role") == "tool"]
    check("has tool result message", len(tool_msgs) == 1)
    check("tool_call_id matches", tool_msgs[0].get("tool_call_id") == "c1")


# ── 8.4 Abort test ──────────────────────────────────────────


def test_abort():
    print("\n=== 8.4 agent_loop abort test ===")

    from src.agent.loop import agent_loop

    state = make_state(abort=True)
    events: list[StreamEvent] = []

    async def run():
        async for ev in agent_loop(state):
            events.append(ev)

    asyncio.run(run())

    check("exit_reason ABORT", state.exit_reason == ExitReason.ABORT)
    check("no events yielded (aborted before LLM call)", len(events) == 0)


# ── 8.5 Max turns test ──────────────────────────────────────


def test_max_turns():
    print("\n=== 8.5 agent_loop max_turns test ===")

    from src.agent.loop import agent_loop

    tc = ToolCallRequest(id="c1", name="shell", arguments={"cmd": "ls"})
    tool_events = [
        StreamEvent(type="tool_end", tool_call=tc),
        StreamEvent(type="usage", usage=Usage(10, 5, 0)),
        StreamEvent(type="done", finish_reason="tool_calls"),
    ]

    # Every turn returns a tool call — should hit max_turns=1
    state = make_state(adapter_events=[tool_events, tool_events], max_turns=1)
    state.orchestrator.dispatch = AsyncMock(return_value=[
        ToolResult(output="ok", success=True),
    ])

    async def run():
        async for _ in agent_loop(state):
            pass

    asyncio.run(run())

    check("exit_reason MAX_TURNS", state.exit_reason == ExitReason.MAX_TURNS)
    check("turn_count is 1", state.turn_count == 1)


# ── 8.6 Error test ──────────────────────────────────────────


def test_error():
    print("\n=== 8.6 agent_loop error test ===")

    from src.agent.loop import agent_loop

    state = make_state()

    async def error_stream(messages, tool_defs, **kwargs):
        raise RuntimeError("LLM exploded")
        yield  # make it a generator  # noqa: E501

    state.adapter.call_stream = error_stream

    events: list[StreamEvent] = []

    async def run():
        async for ev in agent_loop(state):
            events.append(ev)

    asyncio.run(run())

    check("exit_reason ERROR", state.exit_reason == ExitReason.ERROR)
    error_events = [e for e in events if e.type == "error"]
    check("has error event", len(error_events) == 1)
    check("error content", "exploded" in error_events[0].content)


# ── 8.7 Reactive compact test ───────────────────────────────


def test_reactive_compact():
    print("\n=== 8.7 agent_loop reactive compact test ===")

    from unittest.mock import patch

    from src.agent.loop import agent_loop

    call_count = 0

    async def flaky_stream(messages, tool_defs, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("context_length_exceeded: too long")
        yield StreamEvent(type="text_delta", content="ok after compact")
        yield StreamEvent(type="usage", usage=Usage(5, 5, 0))
        yield StreamEvent(type="done", finish_reason="stop")

    state = make_state()
    state.adapter.call_stream = flaky_stream

    compact_called = False
    original_reactive = None

    async def fake_reactive(messages, adapter, model):
        nonlocal compact_called
        compact_called = True
        # Return a mock CompactResult
        result = MagicMock()
        result.messages = messages[-2:]  # keep last 2 messages
        return result

    events: list[StreamEvent] = []

    async def run():
        with patch("src.agent.loop.reactive_compact", side_effect=fake_reactive):
            async for ev in agent_loop(state):
                events.append(ev)

    asyncio.run(run())

    check("reactive_compact was called", compact_called)
    check("has_attempted_reactive_compact set", state.has_attempted_reactive_compact is True)
    check("exit_reason COMPLETED (recovered)", state.exit_reason == ExitReason.COMPLETED)
    check("got text after compact", any(e.type == "text_delta" and e.content == "ok after compact" for e in events))


# ── 8.8 run_agent_to_completion test ─────────────────────────


def test_run_agent_to_completion():
    print("\n=== 8.8 run_agent_to_completion test ===")

    from src.agent.loop import run_agent_to_completion

    state = make_state()

    async def run():
        result = await run_agent_to_completion(state)
        return result

    result = asyncio.run(run())

    check("returns ExitReason", result == ExitReason.COMPLETED)
    check("state.exit_reason set", state.exit_reason == ExitReason.COMPLETED)
    check("messages accumulated", len(state.messages) > 2)


# ── Run all ──────────────────────────────────────────────────


if __name__ == "__main__":
    test_single_turn_text()
    test_multi_turn_tool()
    test_message_accumulation()
    test_abort()
    test_max_turns()
    test_error()
    test_reactive_compact()
    test_run_agent_to_completion()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
