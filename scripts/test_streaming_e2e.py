"""End-to-end streaming tests with real LLM calls.

Tests 10.1 through 10.5 from the streaming tasks.
Requires configured API keys in config/settings.yaml.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.router import route
from src.streaming.events import StreamEvent

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


# ── 10.1 OpenAI real streaming test ─────────────────────────


def test_openai_real_stream():
    print("\n=== 10.1 OpenAI real streaming test ===")

    adapter = route("light")
    events: list[StreamEvent] = []
    text_parts: list[str] = []

    async def run():
        async for ev in adapter.call_stream(
            [{"role": "user", "content": "Say exactly: Hello streaming world"}],
        ):
            events.append(ev)
            if ev.type == "text_delta":
                text_parts.append(ev.content)
                print(ev.content, end="", flush=True)
        print()

    asyncio.run(run())

    types = [e.type for e in events]
    check("has text_delta events", "text_delta" in types)
    check("has usage event", "usage" in types)
    check("has done event", "done" in types)
    check("text_delta count > 1 (actually streaming)", types.count("text_delta") > 1)

    full_text = "".join(text_parts)
    check("accumulated text non-empty", len(full_text) > 0)
    print(f"  Full text: {full_text[:100]}...")

    usage_ev = [e for e in events if e.type == "usage"][0]
    check("usage has input_tokens", usage_ev.usage.input_tokens > 0)
    check("usage has output_tokens", usage_ev.usage.output_tokens > 0)

    done_ev = [e for e in events if e.type == "done"][0]
    check("done has finish_reason", done_ev.finish_reason in ("stop", "end_turn"))


# ── 10.2 Anthropic real streaming test ──────────────────────


def test_anthropic_real_stream():
    print("\n=== 10.2 Anthropic real streaming test ===")

    try:
        adapter = route("strong")
    except Exception as exc:
        print(f"  [SKIP] Anthropic not configured: {exc}")
        return

    events: list[StreamEvent] = []
    text_parts: list[str] = []

    async def run():
        async for ev in adapter.call_stream(
            [{"role": "user", "content": "Say exactly: Hello from Claude streaming"}],
        ):
            events.append(ev)
            if ev.type == "text_delta":
                text_parts.append(ev.content)
                print(ev.content, end="", flush=True)
        print()

    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"  [SKIP] Anthropic API error: {exc}")
        return

    types = [e.type for e in events]
    check("has text_delta events", "text_delta" in types)
    check("has usage event", "usage" in types)
    check("has done event", "done" in types)
    check("text_delta count > 1 (actually streaming)", types.count("text_delta") > 1)

    full_text = "".join(text_parts)
    check("accumulated text non-empty", len(full_text) > 0)
    print(f"  Full text: {full_text[:100]}...")

    usage_ev = [e for e in events if e.type == "usage"][0]
    check("usage has input_tokens", usage_ev.usage.input_tokens > 0)


# ── 10.3 Real streaming tool call test ──────────────────────


def test_real_stream_tool_call():
    print("\n=== 10.3 Real streaming tool call test ===")

    adapter = route("light")
    events: list[StreamEvent] = []

    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        },
    }]

    async def run():
        async for ev in adapter.call_stream(
            [{"role": "user", "content": "What's the weather in Tokyo?"}],
            tools=tools,
        ):
            events.append(ev)
            if ev.type in ("text_delta", "tool_start", "tool_end"):
                print(f"  {ev.type}: {ev.content or ev.name or (ev.tool_call.name if ev.tool_call else '')}")

    asyncio.run(run())

    types = [e.type for e in events]
    check("has tool_start", "tool_start" in types)
    check("has tool_end", "tool_end" in types)
    check("has done", "done" in types)

    tool_end = [e for e in events if e.type == "tool_end"]
    if tool_end:
        tc = tool_end[0].tool_call
        check("tool_call has name", tc.name == "get_weather")
        check("tool_call has arguments", "city" in tc.arguments)
        check("city is Tokyo", "tokyo" in tc.arguments.get("city", "").lower())


# ── 10.4 SSE format validation test ─────────────────────────


def test_sse_format_validation():
    print("\n=== 10.4 SSE format validation test ===")

    adapter = route("light")
    events: list[StreamEvent] = []

    async def run():
        async for ev in adapter.call_stream(
            [{"role": "user", "content": "Say hi"}],
        ):
            events.append(ev)

    asyncio.run(run())

    import json

    for ev in events:
        sse = ev.to_sse()
        check(f"SSE starts with 'event: {ev.type}'", sse.startswith(f"event: {ev.type}\n"))
        check(f"SSE has data line", "\ndata: " in sse)
        check(f"SSE ends with double newline", sse.endswith("\n\n"))

        # Parse data JSON
        data_line = sse.split("data: ")[1].strip()
        try:
            parsed = json.loads(data_line)
            check(f"SSE data is valid JSON ({ev.type})", True)
        except json.JSONDecodeError:
            check(f"SSE data is valid JSON ({ev.type})", False)


# ── 10.5 agent_loop end-to-end streaming test ───────────────


def test_agent_loop_e2e():
    print("\n=== 10.5 agent_loop end-to-end streaming test ===")

    from src.agent.loop import agent_loop
    from src.agent.state import AgentState, ExitReason
    from src.tools.base import ToolContext
    from src.tools.orchestrator import ToolOrchestrator
    from src.tools.registry import ToolRegistry

    events: list[StreamEvent] = []

    async def run():
        # Build state directly with light tier to avoid role-file API key issues
        adapter = route("light")
        registry = ToolRegistry()
        orchestrator = ToolOrchestrator(registry)
        tool_context = ToolContext(
            agent_id="e2e-test",
            run_id="test-e2e-stream",
            project_id=1,
            abort_signal=None,
        )

        state = AgentState(
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Be very brief."},
                {"role": "user", "content": "Say exactly: streaming works"},
            ],
            tools=registry,
            adapter=adapter,
            orchestrator=orchestrator,
            tool_context=tool_context,
        )

        async for ev in agent_loop(state):
            events.append(ev)
            if ev.type == "text_delta":
                print(ev.content, end="", flush=True)
        print()

        return state

    state = asyncio.run(run())

    types = [e.type for e in events]
    check("has text_delta events", "text_delta" in types)
    check("exit_reason COMPLETED", state.exit_reason == ExitReason.COMPLETED)
    check("messages accumulated", len(state.messages) > 2)

    assistant_msgs = [m for m in state.messages if m.get("role") == "assistant"]
    check("has assistant message", len(assistant_msgs) > 0)
    check("assistant has content", assistant_msgs[-1].get("content") is not None)


# ── Run all ──────────────────────────────────────────────────


if __name__ == "__main__":
    test_openai_real_stream()
    test_anthropic_real_stream()
    test_real_stream_tool_call()
    test_sse_format_validation()
    test_agent_loop_e2e()

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
