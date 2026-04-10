"""Error handling tests: node failure → error in state → conditional edge → END."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.graph import PipelineState, _make_node_fn
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


# ── 1. Node failure writes error to state ────────────────

print("\n=== 1. Node failure → error in state ===")


async def test_failure_captures_error():
    node = NodeDefinition(name="bad_node", role="writer", output="draft")

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
        "error": None,
    }

    with patch(
        "src.engine.pipeline._run_node",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM API timeout"),
    ):
        result = await fn(state)

    check("Error captured in return", "error" in result)
    check("Error contains message", "LLM API timeout" in result["error"])
    check("No exception raised (caught)", True)  # If we got here, no exception


asyncio.run(test_failure_captures_error())


# ── 2. Downstream node skips on existing error ──────────

print("\n=== 2. Downstream skips on existing error ===")


async def test_downstream_skips():
    node = NodeDefinition(name="downstream", role="reviewer", output="review", input=["draft"])

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
        "outputs": {"draft": "some content"},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": "upstream node failed: LLM timeout",
    }

    with patch("src.engine.pipeline._run_node", new_callable=AsyncMock) as mock_run:
        result = await fn(state)

    check("Downstream returns empty (no new state)", result == {})
    check("_run_node never called", not mock_run.called)


asyncio.run(test_downstream_skips())


# ── 3. Successful node does not set error ────────────────

print("\n=== 3. Success → no error ===")


async def test_success_no_error():
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
        "user_input": "write something",
        "outputs": {},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    with patch("src.engine.pipeline._run_node", new_callable=AsyncMock, return_value="Done"):
        result = await fn(state)

    check("Success has outputs", "outputs" in result)
    check("Success has no error key", "error" not in result)


asyncio.run(test_success_no_error())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
