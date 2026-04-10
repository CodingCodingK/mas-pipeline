"""Agent loop compact integration tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.state import AgentState, ExitReason
from src.streaming.events import StreamEvent
from src.tools.base import ToolContext


async def _default_stream(msgs, tools):
    yield StreamEvent(type="text_delta", content="Done")
    yield StreamEvent(type="done", finish_reason="stop")

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


def _make_state(messages=None, model="test-model"):
    mock_adapter = AsyncMock()
    mock_adapter.model = model

    mock_adapter.call_stream = _default_stream

    mock_tools = MagicMock()
    mock_tools.list_definitions.return_value = []

    mock_orch = AsyncMock()
    ctx = ToolContext(agent_id="test", run_id="r1")

    return AgentState(
        messages=messages or [{"role": "user", "content": "hello"}],
        adapter=mock_adapter,
        tools=mock_tools,
        orchestrator=mock_orch,
        tool_context=ctx,
    )


def _mock_thresholds(autocompact=1000, blocking=2000):
    from src.agent.compact import CompactThresholds

    return CompactThresholds(
        context_window=3000,
        autocompact_threshold=autocompact,
        blocking_limit=blocking,
    )


# ── 1. TOKEN_LIMIT ExitReason ────────────────────────────────

print("\n=== 1. TOKEN_LIMIT exists ===")

check("TOKEN_LIMIT value", ExitReason.TOKEN_LIMIT == "token_limit")
check("TOKEN_LIMIT is ExitReason", isinstance(ExitReason.TOKEN_LIMIT, ExitReason))


# ── 2. Microcompact runs every turn ─────────────────────────

print("\n=== 2. Microcompact integration ===")


async def test_microcompact_called():
    state = _make_state()

    mock_micro = MagicMock(return_value=state.messages)

    with (
        patch("src.agent.loop.micro_compact", mock_micro),
        patch("src.agent.loop.estimate_tokens", return_value=100),
        patch("src.agent.loop.get_thresholds", return_value=_mock_thresholds()),
        patch("src.agent.loop.get_settings") as mock_settings,
    ):
        mock_settings.return_value.compact.micro_keep_recent = 3
        from src.agent.loop import run_agent_to_completion

        result = await run_agent_to_completion(state)

    check("Microcompact called", mock_micro.called)
    check("Loop completes", result == ExitReason.COMPLETED)


asyncio.run(test_microcompact_called())


# ── 3. Blocking limit triggers TOKEN_LIMIT ───────────────────

print("\n=== 3. Blocking limit ===")


async def test_blocking_limit():
    state = _make_state()

    with (
        patch("src.agent.loop.micro_compact", MagicMock(return_value=state.messages)),
        patch("src.agent.loop.estimate_tokens", return_value=3000),  # exceeds blocking=2000
        patch("src.agent.loop.get_thresholds", return_value=_mock_thresholds()),
        patch("src.agent.loop.get_settings") as mock_settings,
    ):
        mock_settings.return_value.compact.micro_keep_recent = 3
        from src.agent.loop import run_agent_to_completion

        result = await run_agent_to_completion(state)

    check("Blocking limit returns TOKEN_LIMIT", result == ExitReason.TOKEN_LIMIT)


asyncio.run(test_blocking_limit())


# ── 4. Autocompact triggers on threshold ─────────────────────

print("\n=== 4. Autocompact trigger ===")


async def test_autocompact_trigger():
    state = _make_state()

    from src.agent.compact import CompactResult

    mock_compact_result = CompactResult(
        messages=[{"role": "user", "content": "summary"}],
        summary="summary",
        tokens_before=1500,
        tokens_after=200,
    )

    call_count = [0]

    def fake_estimate(msgs):
        call_count[0] += 1
        if call_count[0] <= 1:
            return 1500  # exceeds autocompact=1000, below blocking=2000
        return 200  # after compact

    with (
        patch("src.agent.loop.micro_compact", MagicMock(return_value=state.messages)),
        patch("src.agent.loop.estimate_tokens", side_effect=fake_estimate),
        patch("src.agent.loop.get_thresholds", return_value=_mock_thresholds()),
        patch("src.agent.loop.get_settings") as mock_settings,
        patch("src.agent.loop.auto_compact", AsyncMock(return_value=mock_compact_result)) as mock_auto,
    ):
        mock_settings.return_value.compact.micro_keep_recent = 3
        from src.agent.loop import run_agent_to_completion

        result = await run_agent_to_completion(state)

    check("Autocompact was called", mock_auto.called)
    check("Loop still completes", result == ExitReason.COMPLETED)


asyncio.run(test_autocompact_trigger())


# ── 5. Reactive compact on context_length_exceeded ──────────

print("\n=== 5. Reactive compact ===")


async def test_reactive_compact():
    state = _make_state()

    from src.agent.compact import CompactResult

    mock_compact_result = CompactResult(
        messages=[{"role": "user", "content": "emergency summary"}],
        summary="emergency",
        tokens_before=5000,
        tokens_after=500,
    )

    # First call raises context_length_exceeded, second succeeds
    mock_adapter = AsyncMock()
    mock_adapter.model = "test-model"

    call_count = [0]

    async def fake_call_stream(msgs, tools):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Error: context_length_exceeded")
        yield StreamEvent(type="text_delta", content="Done after reactive")
        yield StreamEvent(type="done", finish_reason="stop")

    mock_adapter.call_stream = fake_call_stream
    state.adapter = mock_adapter

    with (
        patch("src.agent.loop.micro_compact", MagicMock(return_value=state.messages)),
        patch("src.agent.loop.estimate_tokens", return_value=100),
        patch("src.agent.loop.get_thresholds", return_value=_mock_thresholds()),
        patch("src.agent.loop.get_settings") as mock_settings,
        patch("src.agent.loop.reactive_compact", AsyncMock(return_value=mock_compact_result)) as mock_reactive,
    ):
        mock_settings.return_value.compact.micro_keep_recent = 3
        from src.agent.loop import run_agent_to_completion

        result = await run_agent_to_completion(state)

    check("Reactive compact called", mock_reactive.called)
    check("Flag set after reactive", state.has_attempted_reactive_compact)
    check("Loop completes after retry", result == ExitReason.COMPLETED)


asyncio.run(test_reactive_compact())


# ── 6. Second context_length_exceeded → TOKEN_LIMIT ─────────

print("\n=== 6. Second context_length_exceeded ===")


async def test_second_context_error():
    state = _make_state()
    state.has_attempted_reactive_compact = True  # already tried once

    mock_adapter = AsyncMock()
    mock_adapter.model = "test-model"

    async def fail_stream(msgs, tools):
        raise Exception("context_length_exceeded")
        yield  # unreachable

    mock_adapter.call_stream = fail_stream
    state.adapter = mock_adapter

    with (
        patch("src.agent.loop.micro_compact", MagicMock(return_value=state.messages)),
        patch("src.agent.loop.estimate_tokens", return_value=100),
        patch("src.agent.loop.get_thresholds", return_value=_mock_thresholds()),
        patch("src.agent.loop.get_settings") as mock_settings,
    ):
        mock_settings.return_value.compact.micro_keep_recent = 3
        from src.agent.loop import run_agent_to_completion

        result = await run_agent_to_completion(state)

    check("Second error returns TOKEN_LIMIT", result == ExitReason.TOKEN_LIMIT)


asyncio.run(test_second_context_error())


# ── 7. Non-context error still returns ERROR ─────────────────

print("\n=== 7. Non-context error ===")


async def test_non_context_error():
    state = _make_state()

    mock_adapter = AsyncMock()
    mock_adapter.model = "test-model"

    async def fail_stream(msgs, tools):
        raise Exception("connection refused")
        yield  # unreachable

    mock_adapter.call_stream = fail_stream
    state.adapter = mock_adapter

    with (
        patch("src.agent.loop.micro_compact", MagicMock(return_value=state.messages)),
        patch("src.agent.loop.estimate_tokens", return_value=100),
        patch("src.agent.loop.get_thresholds", return_value=_mock_thresholds()),
        patch("src.agent.loop.get_settings") as mock_settings,
    ):
        mock_settings.return_value.compact.micro_keep_recent = 3
        from src.agent.loop import run_agent_to_completion

        result = await run_agent_to_completion(state)

    check("Non-context error returns ERROR", result == ExitReason.ERROR)


asyncio.run(test_non_context_error())


# ── Summary ──────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
