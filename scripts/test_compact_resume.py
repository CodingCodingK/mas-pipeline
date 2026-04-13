"""Compact resume tests: PG round-trip, build_messages slice, circuit breaker.

Covers the scenarios introduced by align-compact-with-cc:
- Append-only compact persistence
- build_messages slices at boundary
- Full PG -> history -> build_messages round-trip matches pre-compact adapter input
- Circuit breaker after 3 consecutive compact failures (silent, no error event)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def _settings():
    s = MagicMock()
    s.context_windows = {}
    s.compact.autocompact_pct = 0.85
    s.compact.blocking_pct = 0.95
    s.compact.micro_keep_recent = 3
    return s


# ── 1. build_messages slices at boundary ───────────────────

print("\n=== 1. build_messages slices at compact boundary ===")

from src.agent.context import build_messages, slice_messages_for_prompt


def test_build_messages_slices_at_boundary():
    history = [
        {"role": "user", "content": "ancient 1"},
        {"role": "assistant", "content": "ancient reply 1"},
        {"role": "user", "content": "ancient 2"},
        {"role": "user", "content": "SUMMARY", "metadata": {"is_compact_summary": True}},
        {"role": "system", "content": "", "metadata": {"is_compact_boundary": True, "turn": 5}},
        {"role": "user", "content": "fresh question"},
        {"role": "assistant", "content": "fresh answer"},
    ]

    msgs = build_messages("SYS", history, "latest user input")

    check("build_messages result starts with system prompt", msgs[0]["role"] == "system")
    # After system: summary (as plain user), then post-boundary entries, then the trailing user input
    check("summary entry emitted as plain user", msgs[1] == {"role": "user", "content": "SUMMARY"})
    check("boundary marker NOT emitted", all("metadata" not in m for m in msgs))
    check("pre-boundary ancient content removed", not any("ancient" in str(m.get("content", "")) for m in msgs))
    check("post-boundary fresh question present", any(m.get("content") == "fresh question" for m in msgs))
    check("trailing user input appended", msgs[-1]["content"] == "latest user input")


test_build_messages_slices_at_boundary()


def test_build_messages_no_boundary_backcompat():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    msgs = build_messages("SYS", history, "next")
    check("backcompat: no boundary returns full history", len(msgs) == 4)
    check("backcompat: ancient user preserved", msgs[1]["content"] == "hi")


test_build_messages_no_boundary_backcompat()


def test_slice_messages_for_prompt_strips_metadata():
    messages = [
        {"role": "user", "content": "pre", "metadata": {"is_compact_summary": False}},
        {"role": "user", "content": "SUMMARY", "metadata": {"is_compact_summary": True}},
        {"role": "system", "content": "", "metadata": {"is_compact_boundary": True}},
        {"role": "user", "content": "after"},
    ]
    sliced = slice_messages_for_prompt(messages)
    check("slice excludes pre-boundary raw", all(m.get("content") != "pre" for m in sliced))
    check("slice strips metadata from all entries", all("metadata" not in m for m in sliced))
    check("slice contains summary as plain user", any(m == {"role": "user", "content": "SUMMARY"} for m in sliced))
    check("slice contains post-boundary user", any(m.get("content") == "after" for m in sliced))


test_slice_messages_for_prompt_strips_metadata()


# ── 2. End-to-end: compact → PG round-trip → build_messages ─

print("\n=== 2. Compact → PG round-trip → build_messages ===")


async def test_pg_roundtrip():
    """Simulate: compact a 50-message conversation, persist to PG, reload, build_messages.
    The reloaded adapter input must equal the pre-persist slice_messages_for_prompt output.
    """
    from src.agent.compact import auto_compact

    original = [{"role": "user", "content": f"Msg {i} " + "x" * 200} for i in range(50)]

    mock_response = MagicMock()
    mock_response.content = "Summary of 50 msgs."
    mock_adapter = AsyncMock()
    mock_adapter.call = AsyncMock(return_value=mock_response)

    with (
        patch("src.agent.compact.get_settings", return_value=_settings()),
        patch("src.agent.compact.get_context_window", return_value=2000),
    ):
        result = await auto_compact(original, mock_adapter, "test-model", turn=4)

    # What the in-memory runner would feed to the LLM next:
    in_mem_slice = slice_messages_for_prompt(result.messages)

    # Simulate PG round-trip: serialize/deserialize (metadata survives as JSONB dict)
    import copy
    pg_stored = copy.deepcopy(result.messages)
    # Simulate resume: build_messages gets the pg_stored list as history
    resumed = build_messages("SYS", pg_stored, "new question")

    # Strip system + trailing user to compare the history portion
    resumed_history = resumed[1:-1]
    check(
        "resume emits same history as in-memory slice",
        resumed_history == in_mem_slice,
        f"len(resume)={len(resumed_history)} len(slice)={len(in_mem_slice)}",
    )
    check(
        "resumed history has no pre-boundary raw content",
        not any("Msg 0 " in str(m.get("content", "")) for m in resumed_history),
    )
    check(
        "resumed history contains summary content",
        any("Summary of 50 msgs." in str(m.get("content", "")) for m in resumed_history),
    )


asyncio.run(test_pg_roundtrip())


# ── 3. Circuit breaker in agent_loop ────────────────────────

print("\n=== 3. Circuit breaker after 3 consecutive compact failures ===")


async def test_circuit_breaker():
    """After 3 consecutive compact failures, state.compact_breaker_tripped flips True
    and further compact attempts are skipped. No error StreamEvent is emitted.
    """
    from src.agent.state import AgentState, ExitReason

    # Build a state whose estimate_tokens exceeds the autocompact threshold
    state = AgentState()
    state.messages = [{"role": "user", "content": "x" * 10000} for _ in range(50)]

    # Mock adapter: on call_stream, yield a "done" event so the loop terminates cleanly
    async def fake_stream(messages, tools):
        from src.llm.adapter import Usage
        from src.streaming.events import StreamEvent
        yield StreamEvent(type="usage", usage=Usage())
        yield StreamEvent(type="done", finish_reason="stop")

    mock_adapter = MagicMock()
    mock_adapter.model = "gpt-4o-mini"
    mock_adapter.call_stream = fake_stream
    state.adapter = mock_adapter

    # Tools: empty
    state.tools = MagicMock()
    state.tools.list_definitions = MagicMock(return_value=[])

    # Abort signal: none
    tool_ctx = MagicMock()
    tool_ctx.abort_signal = None
    state.tool_context = tool_ctx

    # Force compact to always fail
    async def failing_compact(*args, **kwargs):
        raise RuntimeError("compact blew up")

    events_collected = []
    from src.agent import loop as loop_mod

    with (
        patch.object(loop_mod, "auto_compact", side_effect=failing_compact),
        patch.object(loop_mod, "get_thresholds") as gt,
    ):
        # Low threshold so compact always triggers
        gt.return_value = MagicMock(
            context_window=128000,
            autocompact_threshold=1,
            blocking_limit=2,
        )
        # Drive the loop once — it should attempt compact (fail, increment) then proceed
        async for ev in loop_mod.agent_loop(state):
            events_collected.append(ev)

    check("First run: 1 failure recorded", state.consecutive_compact_failures == 1)
    check("First run: breaker not yet tripped", state.compact_breaker_tripped is False)
    check(
        "No error StreamEvent emitted from compact failure",
        not any(getattr(e, "type", None) == "error" for e in events_collected),
    )

    # Reset adapter + exit reason, drive two more turns
    state.exit_reason = None
    with (
        patch.object(loop_mod, "auto_compact", side_effect=failing_compact),
        patch.object(loop_mod, "get_thresholds") as gt,
    ):
        gt.return_value = MagicMock(
            context_window=128000,
            autocompact_threshold=1,
            blocking_limit=2,
        )
        async for _ in loop_mod.agent_loop(state):
            pass
    check("Second run: 2 failures", state.consecutive_compact_failures == 2)

    state.exit_reason = None
    with (
        patch.object(loop_mod, "auto_compact", side_effect=failing_compact),
        patch.object(loop_mod, "get_thresholds") as gt,
    ):
        gt.return_value = MagicMock(
            context_window=128000,
            autocompact_threshold=1,
            blocking_limit=2,
        )
        async for _ in loop_mod.agent_loop(state):
            pass
    check("Third run: breaker tripped", state.compact_breaker_tripped is True)
    check("Third run: 3 failures", state.consecutive_compact_failures == 3)

    # Fourth run: compact should be skipped entirely — we can verify by mocking auto_compact
    # and asserting it's NOT called
    state.exit_reason = None
    compact_call_count = {"n": 0}

    async def counting_compact(*args, **kwargs):
        compact_call_count["n"] += 1
        raise RuntimeError("should not be called")

    with (
        patch.object(loop_mod, "auto_compact", side_effect=counting_compact),
        patch.object(loop_mod, "get_thresholds") as gt,
    ):
        gt.return_value = MagicMock(
            context_window=128000,
            autocompact_threshold=1,
            blocking_limit=2,
        )
        async for _ in loop_mod.agent_loop(state):
            pass
    check("Fourth run: compact skipped (breaker honored)", compact_call_count["n"] == 0)
    check("Fourth run: loop still completes", state.exit_reason == ExitReason.COMPLETED)


asyncio.run(test_circuit_breaker())


# ── Summary ─────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
