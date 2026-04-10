"""Pipeline scheduling tests: reactive execution with MockAdapter.

Tests the execute_pipeline function end-to-end using a mock LLM adapter
to verify parallel startup, dependency ordering, and data flow.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver

from src.engine.pipeline import load_pipeline  # noqa: F401


async def _mem_checkpointer():
    """Return a fresh MemorySaver (no DB, works on Windows ProactorEventLoop)."""
    return MemorySaver()


# Track execution order and timing
execution_log: list[tuple[str, float]] = []
start_time: float = 0


passed = 0
failed_count = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed_count
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed_count += 1
        print(f"  [FAIL] {name} — {detail}")


# ── Test: Parallel node startup ──────────────────────────

async def mock_run_node(node, task_description, project_id, run_id, run_id_int, abort_signal, **kwargs):
    """Mock _run_node that records timing and returns output."""
    execution_log.append((node.name, time.monotonic() - start_time))
    await asyncio.sleep(0.2)  # Simulate LLM call
    return f"Output from {node.name}: processed"


async def test_parallel_startup():
    """Verify that entry nodes with no dependencies start simultaneously."""
    global execution_log, start_time

    print("\n=== Test: Parallel Node Startup ===")

    execution_log = []
    start_time = time.monotonic()

    with (
        patch("src.engine.pipeline._run_node", side_effect=mock_run_node) as _,
        patch("src.engine.pipeline._resolve_run_id_int", return_value=1) as _,
        patch("src.engine.run.update_run_status", new_callable=AsyncMock) as _,
        patch("src.engine.run.finish_run", new_callable=AsyncMock) as _,
        patch("src.db.get_checkpointer", side_effect=_mem_checkpointer) as _,
    ):
        from src.engine.pipeline import execute_pipeline

        result = await execute_pipeline(
            pipeline_name="test_parallel",
            run_id="test-run-001",
            project_id=1,
            user_input="Write a test article",
        )

    check("Pipeline completed", result.status == "completed")
    check("All 6 outputs present", len(result.outputs) == 6, f"got {len(result.outputs)}: {list(result.outputs.keys())}")
    check("Final output is final_article", "final_article" in result.outputs)
    check("Has final_output text", len(result.final_output) > 0)

    log_names = [name for name, _ in execution_log]
    check("All 6 nodes executed", len(log_names) == 6, f"got {len(log_names)}: {log_names}")

    # Entry nodes (researcher, analyst, fact_checker) should start near-simultaneously
    entry_times = {name: t for name, t in execution_log if name in {"researcher", "analyst", "fact_checker"}}
    if len(entry_times) >= 3:
        time_spread = max(entry_times.values()) - min(entry_times.values())
        check("Entry nodes start near-simultaneously",
              time_spread < 0.1,
              f"spread={time_spread:.3f}s")

    # Dependent nodes should start after their dependencies
    dep_times = {name: t for name, t in execution_log}
    if "writer" in dep_times and "researcher" in dep_times:
        check("Writer starts after researcher",
              dep_times["writer"] > dep_times["researcher"],
              f"writer={dep_times['writer']:.3f} researcher={dep_times['researcher']:.3f}")


# ── Test: Linear ordering ────────────────────────────────

async def test_linear_ordering():
    """Verify linear pipeline executes nodes in order."""
    global execution_log, start_time

    print("\n=== Test: Linear Ordering ===")

    execution_log = []
    start_time = time.monotonic()

    with (
        patch("src.engine.pipeline._run_node", side_effect=mock_run_node) as _,
        patch("src.engine.pipeline._resolve_run_id_int", return_value=1) as _,
        patch("src.engine.run.update_run_status", new_callable=AsyncMock) as _,
        patch("src.engine.run.finish_run", new_callable=AsyncMock) as _,
        patch("src.db.get_checkpointer", side_effect=_mem_checkpointer) as _,
    ):
        from src.engine.pipeline import execute_pipeline

        result = await execute_pipeline(
            pipeline_name="test_linear",
            run_id="test-run-002",
            project_id=1,
            user_input="Write a linear test",
        )

    check("Linear pipeline completed", result.status == "completed")
    check("3 outputs present", len(result.outputs) == 3)

    # Nodes should execute sequentially — each starts after previous finishes
    times = [t for _, t in execution_log]
    for i in range(1, len(times)):
        check(f"Node {i+1} starts after node {i}",
              times[i] > times[i-1],
              f"t[{i}]={times[i]:.3f} <= t[{i-1}]={times[i-1]:.3f}")


# ── Test: Data flow ──────────────────────────────────────

async def test_data_flow():
    """Verify upstream outputs are passed to downstream task_description."""
    print("\n=== Test: Data Flow ===")

    received_descriptions: dict[str, str] = {}

    async def tracking_run_node(node, task_description, project_id, run_id, run_id_int, abort_signal, **kwargs):
        received_descriptions[node.name] = task_description
        await asyncio.sleep(0.1)
        return f"Output from {node.name}"

    with (
        patch("src.engine.pipeline._run_node", side_effect=tracking_run_node) as _,
        patch("src.engine.pipeline._resolve_run_id_int", return_value=1) as _,
        patch("src.engine.run.update_run_status", new_callable=AsyncMock) as _,
        patch("src.engine.run.finish_run", new_callable=AsyncMock) as _,
        patch("src.db.get_checkpointer", side_effect=_mem_checkpointer) as _,
    ):
        from src.engine.pipeline import execute_pipeline

        result = await execute_pipeline(
            pipeline_name="test_linear",
            run_id="test-run-003",
            project_id=1,
            user_input="Original user input",
        )

    check("Pipeline completed", result.status == "completed")

    # Entry node (researcher) should get raw user_input
    check("Entry node gets user_input",
          received_descriptions["researcher"] == "Original user input",
          f"got: {received_descriptions.get('researcher', 'N/A')[:50]}")

    # Writer should have upstream output in description
    writer_desc = received_descriptions.get("writer", "")
    check("Writer gets upstream output",
          "## findings" in writer_desc,
          f"got: {writer_desc[:100]}")
    check("Writer desc has researcher content",
          "Output from researcher" in writer_desc,
          f"got: {writer_desc[:150]}")

    # Reviewer should have writer's output
    reviewer_desc = received_descriptions.get("reviewer", "")
    check("Reviewer gets upstream output",
          "## draft" in reviewer_desc,
          f"got: {reviewer_desc[:100]}")


# ── Run all tests ────────────────────────────────────────

async def main():
    await test_parallel_startup()
    await test_linear_ordering()
    await test_data_flow()

    print(f"\n{'='*50}")
    print(f"Total: {passed + failed_count} | Passed: {passed} | Failed: {failed_count}")
    if failed_count > 0:
        sys.exit(1)
    else:
        print("All checks passed!")


asyncio.run(main())
