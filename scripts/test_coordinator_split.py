"""Coordinator split test: run_coordinator only does autonomous mode."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.coordinator import CoordinatorResult, run_coordinator
from src.agent.state import AgentState, ExitReason
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


# ── 1. CoordinatorResult has no 'mode' field ────────────

print("\n=== 1. CoordinatorResult fields ===")

r = CoordinatorResult(run_id="r1", output="test")
check("No 'mode' attribute", not hasattr(r, "mode"))
check("No 'node_outputs' attribute", not hasattr(r, "node_outputs"))
check("Has run_id", r.run_id == "r1")
check("Has output", r.output == "test")
check("agent_runs default None", r.agent_runs is None)


# ── 2. run_coordinator does autonomous mode ──────────────

print("\n=== 2. run_coordinator autonomous ===")


async def test_autonomous():
    mock_wf_run = MagicMock()
    mock_wf_run.run_id = "run_auto"
    mock_wf_run.id = 1

    mock_state = AgentState()
    mock_state.messages = [
        {"role": "system", "content": "You are coordinator"},
        {"role": "assistant", "content": "Task done."},
    ]
    mock_state.tool_context = ToolContext(agent_id="test", run_id="run_auto")

    with (
        patch("src.engine.run.create_run", new_callable=AsyncMock, return_value=mock_wf_run),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, return_value=mock_state),
        patch("src.engine.coordinator.run_coordinator_to_completion", new_callable=AsyncMock),
        patch("src.tools.builtins.spawn_agent.extract_final_output", return_value="Task done."),
        patch("src.agent.runs.list_agent_runs", new_callable=AsyncMock, return_value=[]),
        patch("src.engine.run.finish_run", new_callable=AsyncMock),
    ):
        result = await run_coordinator(project_id=1, user_input="Do something")

    check("Result is CoordinatorResult", isinstance(result, CoordinatorResult))
    check("Output correct", result.output == "Task done.")
    check("Run ID set", result.run_id == "run_auto")
    check("Agent runs empty", result.agent_runs == [])


asyncio.run(test_autonomous())


# ── 3. run_coordinator does NOT reference execute_pipeline ──

print("\n=== 3. No execute_pipeline reference ===")

import src.engine.coordinator as coord_mod
source = Path(coord_mod.__file__).read_text(encoding="utf-8")
check("No execute_pipeline import", "execute_pipeline" not in source)
check("No pipeline mode routing", "'pipeline'" not in source or "mode='pipeline'" not in source)


# ── 4. run_coordinator failure handling ──────────────────

print("\n=== 4. Failure handling ===")


async def test_failure():
    mock_wf_run = MagicMock()
    mock_wf_run.run_id = "run_fail"
    mock_wf_run.id = 2

    with (
        patch("src.engine.run.create_run", new_callable=AsyncMock, return_value=mock_wf_run),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, side_effect=RuntimeError("agent boom")),
        patch("src.engine.run.finish_run", new_callable=AsyncMock) as mock_finish,
    ):
        try:
            await run_coordinator(project_id=1, user_input="test")
            check("Exception propagates", False, "no exception")
        except RuntimeError as e:
            check("Exception propagates", "agent boom" in str(e))

    # Verify finish_run was called with FAILED
    from src.engine.run import RunStatus
    check("Run marked FAILED", mock_finish.called)
    check("FAILED status", mock_finish.call_args[0][1] == RunStatus.FAILED)


asyncio.run(test_failure())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
