"""Coordinator unit tests: CoordinatorResult, run_coordinator autonomous mode."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.coordinator import CoordinatorResult, run_coordinator
from src.agent.state import AgentState
from src.tools.base import ToolContext

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


# ── 1. CoordinatorResult construction ─────────────────────

print("\n=== 1. CoordinatorResult construction ===")

r1 = CoordinatorResult(
    run_id="abc123",
    output="Task completed",
)
check("run_id", r1.run_id == "abc123")
check("output", r1.output == "Task completed")
check("agent_runs default None", r1.agent_runs is None)
check("no mode attribute", not hasattr(r1, "mode"))
check("no node_outputs attribute", not hasattr(r1, "node_outputs"))

r2 = CoordinatorResult(
    run_id="def456",
    output="Done",
    agent_runs=[{"id": 1, "role": "general", "status": "completed", "result": "ok"}],
)
check("agent_runs populated", len(r2.agent_runs) == 1)


# ── 2. run_coordinator: autonomous mode happy path ───────

print("\n=== 2. run_coordinator autonomous ===")


async def test_run_coordinator_autonomous():
    """run_coordinator creates WorkflowRun, runs loop, extracts output."""

    mock_wf_run = MagicMock()
    mock_wf_run.run_id = "run_def"
    mock_wf_run.id = 2

    mock_state = AgentState()
    mock_state.messages = [
        {"role": "system", "content": "You are coordinator"},
        {"role": "user", "content": "Do something"},
        {"role": "assistant", "content": "Here is the result."},
    ]
    mock_state.tool_context = ToolContext(agent_id="test", run_id="run_def")

    with (
        patch("src.engine.run.create_run", new_callable=AsyncMock, return_value=mock_wf_run),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, return_value=mock_state),
        patch("src.engine.coordinator.run_coordinator_to_completion", new_callable=AsyncMock),
        patch("src.tools.builtins.spawn_agent.extract_final_output", return_value="Here is the result."),
        patch("src.agent.runs.list_agent_runs", new_callable=AsyncMock, return_value=[]),
        patch("src.engine.run.finish_run", new_callable=AsyncMock),
    ):
        result = await run_coordinator(project_id=2, user_input="Do something")

    check("Autonomous mode output", result.output == "Here is the result.")
    check("Autonomous mode agent_runs", result.agent_runs == [])
    check("Autonomous mode run_id", result.run_id == "run_def")


asyncio.run(test_run_coordinator_autonomous())


# ── 3. run_coordinator: failure marks run FAILED ─────────

print("\n=== 3. run_coordinator failure handling ===")


async def test_run_coordinator_failure():
    mock_wf_run = MagicMock()
    mock_wf_run.run_id = "run_fail"
    mock_wf_run.id = 3

    with (
        patch("src.engine.run.create_run", new_callable=AsyncMock, return_value=mock_wf_run),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        patch("src.engine.run.finish_run", new_callable=AsyncMock) as mock_finish,
    ):
        try:
            await run_coordinator(project_id=3, user_input="test")
            check("Exception propagates", False, "no exception")
        except RuntimeError as e:
            check("Exception propagates", "boom" in str(e))

    from src.engine.run import RunStatus
    check("finish_run called", mock_finish.called)
    check("Marked FAILED", mock_finish.call_args[0][1] == RunStatus.FAILED)


asyncio.run(test_run_coordinator_failure())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
