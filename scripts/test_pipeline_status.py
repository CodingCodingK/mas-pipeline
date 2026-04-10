"""get_pipeline_status tests: running/paused/completed status query."""

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
        print(f"  [FAIL] {name} — {detail}")


# ── 1. Running pipeline status ───────────────────────────

print("\n=== 1. Running pipeline status ===")


async def test_status_running():
    from src.engine.pipeline import get_pipeline_status

    mock_run = MagicMock()
    mock_run.status = "running"
    mock_run.pipeline = "test"

    with patch("src.engine.run.get_run", new_callable=AsyncMock, return_value=mock_run):
        result = await get_pipeline_status("r1")

    check("Status is running", result["status"] == "running")
    check("Paused_at is None", result["paused_at"] is None)


asyncio.run(test_status_running())


# ── 2. Completed pipeline status ────────────────────────

print("\n=== 2. Completed pipeline status ===")


async def test_status_completed():
    from src.engine.pipeline import get_pipeline_status

    mock_run = MagicMock()
    mock_run.status = "completed"
    mock_run.pipeline = "test"

    with patch("src.engine.run.get_run", new_callable=AsyncMock, return_value=mock_run):
        result = await get_pipeline_status("r1")

    check("Status is completed", result["status"] == "completed")
    check("Paused_at is None", result["paused_at"] is None)


asyncio.run(test_status_completed())


# ── 3. Failed pipeline status ───────────────────────────

print("\n=== 3. Failed pipeline status ===")


async def test_status_failed():
    from src.engine.pipeline import get_pipeline_status

    mock_run = MagicMock()
    mock_run.status = "failed"
    mock_run.pipeline = "test"

    with patch("src.engine.run.get_run", new_callable=AsyncMock, return_value=mock_run):
        result = await get_pipeline_status("r1")

    check("Status is failed", result["status"] == "failed")
    check("Paused_at is None", result["paused_at"] is None)


asyncio.run(test_status_failed())


# ── 4. Paused pipeline status with paused_at ────────────

print("\n=== 4. Paused pipeline status ===")


async def test_status_paused():
    from src.engine.pipeline import get_pipeline_status

    mock_run = MagicMock()
    mock_run.status = "paused"
    mock_run.pipeline = "test_linear"

    # Mock graph state showing paused at reviewer_interrupt
    mock_graph_state = MagicMock()
    mock_graph_state.next = ("reviewer_interrupt",)

    mock_compiled = MagicMock()
    mock_compiled.aget_state = AsyncMock(return_value=mock_graph_state)

    mock_cp = AsyncMock()
    mock_cp.aget_tuple = AsyncMock(return_value=MagicMock(metadata={}))

    with (
        patch("src.engine.run.get_run", new_callable=AsyncMock, return_value=mock_run),
        patch("src.db.get_checkpointer", new_callable=AsyncMock, return_value=mock_cp),
        patch("src.engine.graph.build_graph", return_value=mock_compiled),
        patch("src.engine.pipeline.load_pipeline") as mock_load,
        patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1),
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.nodes = []
        mock_load.return_value = mock_pipeline

        result = await get_pipeline_status("r1")

    check("Status is paused", result["status"] == "paused")
    check("Paused_at is reviewer", result["paused_at"] == "reviewer")


asyncio.run(test_status_paused())


# ── 5. Non-existent run → ValueError ────────────────────

print("\n=== 5. Non-existent run ===")


async def test_status_not_found():
    from src.engine.pipeline import get_pipeline_status

    with patch("src.engine.run.get_run", new_callable=AsyncMock, return_value=None):
        try:
            await get_pipeline_status("nonexistent")
            check("Not found raises", False, "no exception")
        except ValueError as e:
            check("Not found raises ValueError", "not found" in str(e).lower())


asyncio.run(test_status_not_found())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
