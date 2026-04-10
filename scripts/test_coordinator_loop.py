"""coordinator_loop tests: mock agent_loop (async_generator) + notification queue."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.state import AgentState, ExitReason
from src.engine.coordinator import coordinator_loop
from src.tools.base import ToolContext
from src.tools.builtins.spawn_agent import format_task_notification

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


async def consume(state: AgentState) -> ExitReason | None:
    """Run coordinator_loop to completion, return final exit_reason."""
    async for _ in coordinator_loop(state):
        pass
    return state.exit_reason


def make_mock_loop(step_fn):
    """Wrap a sync step function into an async generator compatible with agent_loop signature.

    step_fn(state, call_count) -> None; must set state.exit_reason before returning.
    """
    call_count = [0]

    async def mock_agent_loop(s):
        call_count[0] += 1
        step_fn(s, call_count[0])
        if False:  # pragma: no cover — make this an async generator
            yield

    mock_agent_loop.call_count = call_count  # type: ignore[attr-defined]
    return mock_agent_loop


# ── 1. Queue initialization ─────────────────────────────

print("\n=== 1. Queue initialization ===")


async def test_queue_init():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")

    def step(s, n):
        s.exit_reason = ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=make_mock_loop(step)):
        await consume(state)

    check("notification_queue is asyncio.Queue", isinstance(state.notification_queue, asyncio.Queue))
    check("running_agent_count is 0", state.running_agent_count == 0)


asyncio.run(test_queue_init())

# ── 2. Single notification cycle ─────────────────────────

print("\n=== 2. Single notification cycle ===")


async def test_single_notification():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    calls = []

    def step(s, n):
        calls.append(n)
        if n == 1:
            s.running_agent_count = 1

            async def push():
                await asyncio.sleep(0.01)
                notif_msg = format_task_notification(10, "general", "completed", "result A")
                await s.notification_queue.put({
                    "agent_run_id": 10,
                    "role": "general",
                    "status": "completed",
                    "result": "result A",
                    "message": notif_msg,
                })
                s.running_agent_count = 0

            asyncio.create_task(push())
            s.exit_reason = ExitReason.COMPLETED
        else:
            s.exit_reason = ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=make_mock_loop(step)):
        exit_reason = await consume(state)

    check("Exit reason COMPLETED", exit_reason == ExitReason.COMPLETED)
    check("agent_loop called 2 times", len(calls) == 2)

    user_msgs = [m for m in state.messages if m["role"] == "user"]
    check("One notification injected", len(user_msgs) == 1)
    check("Notification has agent-run-id", "<agent-run-id>10</agent-run-id>" in user_msgs[0]["content"])


asyncio.run(test_single_notification())

# ── 3. Multiple notifications drained at once ────────────

print("\n=== 3. Multiple notifications drained ===")


async def test_drain_multiple():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    calls = []

    def step(s, n):
        calls.append(n)
        if n == 1:
            s.running_agent_count = 2

            async def push_both():
                await asyncio.sleep(0.01)
                for i, role in enumerate(["writer", "researcher"], start=20):
                    msg = format_task_notification(i, role, "completed", f"output_{role}")
                    await s.notification_queue.put({
                        "agent_run_id": i,
                        "role": role,
                        "status": "completed",
                        "result": f"output_{role}",
                        "message": msg,
                    })
                s.running_agent_count = 0

            asyncio.create_task(push_both())
            s.exit_reason = ExitReason.COMPLETED
        else:
            s.exit_reason = ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=make_mock_loop(step)):
        await consume(state)

    user_msgs = [m for m in state.messages if m["role"] == "user"]
    check("Two notifications injected", len(user_msgs) == 2)
    check("writer or researcher present",
          any("writer" in m["content"] or "researcher" in m["content"] for m in user_msgs))
    check("agent_loop called 2 times", len(calls) == 2)


asyncio.run(test_drain_multiple())

# ── 4. Multi-round coordination ──────────────────────────

print("\n=== 4. Multi-round coordination ===")


async def test_multi_round():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    calls = []

    def step(s, n):
        calls.append(n)
        if n == 1:
            s.running_agent_count = 1

            async def push_a():
                await asyncio.sleep(0.01)
                msg = format_task_notification(1, "agent_a", "completed", "result_a")
                await s.notification_queue.put({
                    "agent_run_id": 1, "role": "agent_a",
                    "status": "completed", "result": "result_a", "message": msg,
                })
                s.running_agent_count = 0

            asyncio.create_task(push_a())
            s.exit_reason = ExitReason.COMPLETED
        elif n == 2:
            s.running_agent_count = 1

            async def push_b():
                await asyncio.sleep(0.01)
                msg = format_task_notification(2, "agent_b", "completed", "result_b")
                await s.notification_queue.put({
                    "agent_run_id": 2, "role": "agent_b",
                    "status": "completed", "result": "result_b", "message": msg,
                })
                s.running_agent_count = 0

            asyncio.create_task(push_b())
            s.exit_reason = ExitReason.COMPLETED
        else:
            s.exit_reason = ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=make_mock_loop(step)):
        exit_reason = await consume(state)

    check("Multi-round exit COMPLETED", exit_reason == ExitReason.COMPLETED)
    check("agent_loop called 3 times", len(calls) == 3)
    user_msgs = [m for m in state.messages if m["role"] == "user"]
    check("Two notifications total", len(user_msgs) == 2)
    check("Agent A notification present", any("agent_a" in m["content"] for m in user_msgs))
    check("Agent B notification present", any("agent_b" in m["content"] for m in user_msgs))


asyncio.run(test_multi_round())

# ── 5. Failed agent notification ─────────────────────────

print("\n=== 5. Failed agent notification ===")


async def test_failed_notification():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")

    def step(s, n):
        if n == 1:
            s.running_agent_count = 1

            async def push_fail():
                await asyncio.sleep(0.01)
                msg = format_task_notification(99, "buggy", "failed", "[ERROR] timeout")
                await s.notification_queue.put({
                    "agent_run_id": 99, "role": "buggy",
                    "status": "failed", "result": "[ERROR] timeout", "message": msg,
                })
                s.running_agent_count = 0

            asyncio.create_task(push_fail())
        s.exit_reason = ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=make_mock_loop(step)):
        await consume(state)

    user_msgs = [m for m in state.messages if m["role"] == "user"]
    check("Failed notification injected", len(user_msgs) == 1)
    check("Contains failed status", "<status>failed</status>" in user_msgs[0]["content"])
    check("Contains error detail", "timeout" in user_msgs[0]["content"])


asyncio.run(test_failed_notification())

# ── 6. Zero LLM calls during wait ───────────────────────

print("\n=== 6. Zero LLM calls during wait ===")


async def test_zero_llm_during_wait():
    """Verify only 2 agent_loop invocations (no polling during wait)."""
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    llm_calls = [0]

    def step(s, n):
        llm_calls[0] += 1
        if n == 1:
            s.running_agent_count = 1

            async def push():
                await asyncio.sleep(0.05)
                msg = format_task_notification(1, "slow", "completed", "ok")
                await s.notification_queue.put({
                    "agent_run_id": 1, "role": "slow",
                    "status": "completed", "result": "ok", "message": msg,
                })
                s.running_agent_count = 0

            asyncio.create_task(push())
        s.exit_reason = ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=make_mock_loop(step)):
        await consume(state)

    check("Only 2 agent_loop calls (not polling)", llm_calls[0] == 2)


asyncio.run(test_zero_llm_during_wait())

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
