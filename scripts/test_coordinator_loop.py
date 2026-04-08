"""coordinator_loop tests: mock agent_loop + notification queue, verify injection and re-entry."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


# ── 1. Queue initialization ─────────────────────────────

print("\n=== 1. Queue initialization ===")


async def test_queue_init():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")

    with patch("src.agent.loop.agent_loop", new_callable=AsyncMock) as mock:
        mock.return_value = ExitReason.COMPLETED
        await coordinator_loop(state)

    check("notification_queue is asyncio.Queue", isinstance(state.notification_queue, asyncio.Queue))
    check("running_agent_count is 0", state.running_agent_count == 0)


asyncio.run(test_queue_init())

# ── 2. Single notification cycle ─────────────────────────

print("\n=== 2. Single notification cycle ===")


async def test_single_notification():
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    calls = []

    async def mock_agent_loop(s):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            s.running_agent_count = 1
            notif_msg = format_task_notification(10, "general", "completed", "result A")
            async def push():
                await asyncio.sleep(0.01)
                await s.notification_queue.put({
                    "agent_run_id": 10,
                    "role": "general",
                    "status": "completed",
                    "result": "result A",
                    "message": notif_msg,
                })
                s.running_agent_count = 0
            asyncio.create_task(push())
            return ExitReason.COMPLETED
        return ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=mock_agent_loop):
        exit_reason = await coordinator_loop(state)

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

    async def mock_agent_loop(s):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
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
            return ExitReason.COMPLETED
        return ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=mock_agent_loop):
        await coordinator_loop(state)

    user_msgs = [m for m in state.messages if m["role"] == "user"]
    check("Two notifications injected", len(user_msgs) == 2)
    check("First notification is writer or researcher",
          any("writer" in m["content"] or "researcher" in m["content"] for m in user_msgs))
    check("agent_loop called 2 times (drain before re-entry)", len(calls) == 2)


asyncio.run(test_drain_multiple())

# ── 4. Multi-round coordination ──────────────────────────

print("\n=== 4. Multi-round coordination ===")


async def test_multi_round():
    """Simulate: spawn 1 → notification → spawn 1 more → notification → done."""
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    calls = []

    async def mock_agent_loop(s):
        calls.append(len(calls) + 1)
        round_num = len(calls)

        if round_num == 1:
            # First round: spawn agent A
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
            return ExitReason.COMPLETED

        elif round_num == 2:
            # Second round: process A's result, spawn agent B
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
            return ExitReason.COMPLETED

        else:
            # Third round: all done, synthesize
            return ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=mock_agent_loop):
        exit_reason = await coordinator_loop(state)

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
    calls = []

    async def mock_agent_loop(s):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
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
            return ExitReason.COMPLETED
        return ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=mock_agent_loop):
        await coordinator_loop(state)

    user_msgs = [m for m in state.messages if m["role"] == "user"]
    check("Failed notification injected", len(user_msgs) == 1)
    check("Contains failed status", "<status>failed</status>" in user_msgs[0]["content"])
    check("Contains error detail", "timeout" in user_msgs[0]["content"])


asyncio.run(test_failed_notification())

# ── 6. Zero LLM calls during wait ───────────────────────

print("\n=== 6. Zero LLM calls during wait ===")


async def test_zero_llm_during_wait():
    """Verify that only asyncio.Queue ops happen during wait, no LLM calls."""
    state = AgentState()
    state.tool_context = ToolContext(agent_id="t", run_id="r")
    llm_call_count = 0

    async def mock_agent_loop(s):
        nonlocal llm_call_count
        llm_call_count += 1
        if llm_call_count == 1:
            s.running_agent_count = 1
            async def push():
                await asyncio.sleep(0.05)  # Simulate slow agent
                msg = format_task_notification(1, "slow", "completed", "ok")
                await s.notification_queue.put({
                    "agent_run_id": 1, "role": "slow",
                    "status": "completed", "result": "ok", "message": msg,
                })
                s.running_agent_count = 0
            asyncio.create_task(push())
            return ExitReason.COMPLETED
        return ExitReason.COMPLETED

    with patch("src.agent.loop.agent_loop", side_effect=mock_agent_loop):
        await coordinator_loop(state)

    check("Only 2 agent_loop calls (not polling)", llm_call_count == 2)


asyncio.run(test_zero_llm_during_wait())

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
