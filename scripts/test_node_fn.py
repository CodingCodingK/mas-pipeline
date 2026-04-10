"""Node function tests: entry/non-entry node behavior, error capture."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.graph import PipelineState, _make_interrupt_fn, _make_node_fn
from src.engine.pipeline import NodeDefinition

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


abort = asyncio.Event()


# ── 1. Entry node receives user_input ────────────────────

print("\n=== 1. Entry node (no input deps) ===")


async def test_entry_node():
    node = NodeDefinition(name="researcher", role="researcher", output="research")

    fn = _make_node_fn(
        node,
        run_id="r1",
        run_id_int=1,
        abort_signal=abort,
        permission_mode="normal",
        mcp_manager=None,
    )

    state: PipelineState = {
        "user_input": "Write about AI",
        "outputs": {},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    with patch("src.engine.pipeline._run_node", new_callable=AsyncMock, return_value="AI research results") as mock_run:
        result = await fn(state)

    check("Entry node returns output dict", "outputs" in result)
    check("Entry node output key correct", result["outputs"] == {"research": "AI research results"})
    # Verify _run_node was called with user_input as task_description
    call_kwargs = mock_run.call_args
    check("Entry node task_desc is user_input", call_kwargs.kwargs["task_description"] == "Write about AI")


asyncio.run(test_entry_node())


# ── 2. Non-entry node receives upstream outputs ─────────

print("\n=== 2. Non-entry node (has input deps) ===")


async def test_nonentry_node():
    node = NodeDefinition(name="writer", role="writer", output="draft", input=["research"])

    fn = _make_node_fn(
        node,
        run_id="r1",
        run_id_int=1,
        abort_signal=abort,
        permission_mode="normal",
        mcp_manager=None,
    )

    state: PipelineState = {
        "user_input": "Write about AI",
        "outputs": {"research": "AI research data here"},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    with patch("src.engine.pipeline._run_node", new_callable=AsyncMock, return_value="Draft text") as mock_run:
        result = await fn(state)

    check("Non-entry node returns output", result["outputs"] == {"draft": "Draft text"})
    # Verify task_description contains upstream output
    call_kwargs = mock_run.call_args
    task_desc = call_kwargs.kwargs["task_description"]
    check("Task desc contains upstream output", "AI research data here" in task_desc)
    check("Task desc contains input label", "research" in task_desc)


asyncio.run(test_nonentry_node())


# ── 3. Node failure writes error to state ────────────────

print("\n=== 3. Node failure → error in state ===")


async def test_node_failure():
    node = NodeDefinition(name="writer", role="writer", output="draft")

    fn = _make_node_fn(
        node,
        run_id="r1",
        run_id_int=1,
        abort_signal=abort,
        permission_mode="normal",
        mcp_manager=None,
    )

    state: PipelineState = {
        "user_input": "Write about AI",
        "outputs": {},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    with patch(
        "src.engine.pipeline._run_node",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Agent crashed"),
    ):
        result = await fn(state)

    check("Failed node returns error", "error" in result)
    check("Error message captured", "Agent crashed" in result["error"])
    check("No outputs on failure", "outputs" not in result or result.get("outputs") is None)


asyncio.run(test_node_failure())


# ── 4. Node skips if error already set ───────────────────

print("\n=== 4. Short-circuit on existing error ===")


async def test_skip_on_error():
    node = NodeDefinition(name="reviewer", role="reviewer", output="review")

    fn = _make_node_fn(
        node,
        run_id="r1",
        run_id_int=1,
        abort_signal=abort,
        permission_mode="normal",
        mcp_manager=None,
    )

    state: PipelineState = {
        "user_input": "test",
        "outputs": {},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": "previous node failed",
    }

    with patch("src.engine.pipeline._run_node", new_callable=AsyncMock) as mock_run:
        result = await fn(state)

    check("Skipped node returns empty", result == {})
    check("_run_node NOT called", not mock_run.called)


asyncio.run(test_skip_on_error())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
