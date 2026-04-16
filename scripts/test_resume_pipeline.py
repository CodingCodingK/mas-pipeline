"""resume_pipeline tests: normal resume, no checkpoint error, feedback resume."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.pipeline import PipelineResult

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


def _make_mock_compiled(final_state: dict, next_nodes: tuple = ()):
    """Create a mock compiled graph that returns the given final_state."""
    mock_compiled = AsyncMock()
    mock_compiled.ainvoke = AsyncMock(return_value=final_state)

    mock_graph_state = MagicMock()
    mock_graph_state.next = next_nodes
    mock_compiled.aget_state = AsyncMock(return_value=mock_graph_state)
    return mock_compiled


def _make_mock_checkpointer(has_checkpoint: bool = True):
    """Create a mock checkpointer."""
    mock_cp = AsyncMock()
    if has_checkpoint:
        mock_cp.aget = AsyncMock(return_value={"some": "checkpoint"})
    else:
        mock_cp.aget = AsyncMock(return_value=None)
    return mock_cp


# ── 1. Normal resume → completed ────────────────────────

print("\n=== 1. Normal resume → completed ===")


async def test_resume_completed():
    from src.engine.pipeline import resume_pipeline

    final_state = {
        "user_input": "Write a blog",
        "outputs": {"draft": "content", "review": "approved"},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    mock_compiled = _make_mock_compiled(final_state, next_nodes=())
    mock_cp = _make_mock_checkpointer(has_checkpoint=True)

    with (
        patch("src.engine.pipeline.resolve_pipeline_file", return_value="test.yaml"),
        patch("src.engine.pipeline.load_pipeline") as mock_load,
        patch("src.db.get_checkpointer", new_callable=AsyncMock, return_value=mock_cp),
        patch("src.engine.graph.build_graph", return_value=mock_compiled),
        patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.engine.run.finish_run", new_callable=AsyncMock),
        patch("src.engine.pipeline._fire_pipeline_hook", new_callable=AsyncMock),
        patch("src.mcp.manager.MCPManager") as MockMCP,
    ):
        # Mock pipeline definition
        mock_pipeline = MagicMock()
        mock_pipeline.nodes = [
            MagicMock(name="writer", output="draft", input=[]),
            MagicMock(name="reviewer", output="review", input=["draft"]),
        ]
        mock_load.return_value = mock_pipeline

        # Mock MCP
        mock_mcp_instance = AsyncMock()
        MockMCP.return_value = mock_mcp_instance

        result = await resume_pipeline(
            pipeline_name="test",
            run_id="r1",
            project_id=1,
            feedback="approved",
        )

    check("Resume returns PipelineResult", isinstance(result, PipelineResult))
    check("Status is completed", result.status == "completed")
    check("Outputs preserved", "draft" in result.outputs)
    check("No error", result.error is None)
    check("Not paused", result.paused_at is None)

    # Verify ainvoke was called with Command(resume=...)
    invoke_args = mock_compiled.ainvoke.call_args
    from langgraph.types import Command
    cmd = invoke_args[0][0]
    check("Called with Command", isinstance(cmd, Command))
    check("Command has feedback", cmd.resume == "approved")


asyncio.run(test_resume_completed())


# ── 2. Resume non-existent checkpoint → ValueError ──────

print("\n=== 2. No checkpoint → ValueError ===")


async def test_resume_no_checkpoint():
    from src.engine.pipeline import resume_pipeline

    mock_cp = _make_mock_checkpointer(has_checkpoint=False)

    with (
        patch("src.engine.pipeline.resolve_pipeline_file", return_value="test.yaml"),
        patch("src.engine.pipeline.load_pipeline"),
        patch("src.db.get_checkpointer", new_callable=AsyncMock, return_value=mock_cp),
    ):
        try:
            await resume_pipeline(
                pipeline_name="test",
                run_id="nonexistent",
                project_id=1,
            )
            check("No checkpoint raises", False, "no exception")
        except ValueError as e:
            check("No checkpoint raises ValueError", "No checkpoint" in str(e))


asyncio.run(test_resume_no_checkpoint())


# ── 3. Resume → paused again (second interrupt) ─────────

print("\n=== 3. Resume → paused again ===")


async def test_resume_paused_again():
    from src.engine.pipeline import resume_pipeline

    final_state = {
        "user_input": "test",
        "outputs": {"draft": "content"},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    # Graph paused at editor_interrupt
    mock_compiled = _make_mock_compiled(final_state, next_nodes=("editor_interrupt",))
    mock_cp = _make_mock_checkpointer(has_checkpoint=True)

    with (
        patch("src.engine.pipeline.resolve_pipeline_file", return_value="test.yaml"),
        patch("src.engine.pipeline.load_pipeline") as mock_load,
        patch("src.db.get_checkpointer", new_callable=AsyncMock, return_value=mock_cp),
        patch("src.engine.graph.build_graph", return_value=mock_compiled),
        patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock) as mock_status,
        patch("src.engine.pipeline._fire_pipeline_hook", new_callable=AsyncMock),
        patch("src.mcp.manager.MCPManager") as MockMCP,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.nodes = [MagicMock(name="w", output="draft", input=[])]
        mock_load.return_value = mock_pipeline
        MockMCP.return_value = AsyncMock()

        result = await resume_pipeline(
            pipeline_name="test",
            run_id="r1",
            project_id=1,
        )

    check("Status is paused", result.status == "paused")
    check("Paused at editor", result.paused_at == "editor")
    # Verify PAUSED status was set
    from src.engine.run import RunStatus
    paused_calls = [c for c in mock_status.call_args_list if c[0][1] == RunStatus.PAUSED]
    check("RunStatus.PAUSED was set", len(paused_calls) == 1)


asyncio.run(test_resume_paused_again())


# ── 4. Resume with None feedback ────────────────────────

print("\n=== 4. Resume with None feedback ===")


async def test_resume_no_feedback():
    from src.engine.pipeline import resume_pipeline

    final_state = {
        "user_input": "test",
        "outputs": {"out": "done"},
        "run_id": "r1",
        "project_id": 1,
        "permission_mode": "normal",
        "error": None,
    }

    mock_compiled = _make_mock_compiled(final_state, next_nodes=())
    mock_cp = _make_mock_checkpointer(has_checkpoint=True)

    with (
        patch("src.engine.pipeline.resolve_pipeline_file", return_value="test.yaml"),
        patch("src.engine.pipeline.load_pipeline") as mock_load,
        patch("src.db.get_checkpointer", new_callable=AsyncMock, return_value=mock_cp),
        patch("src.engine.graph.build_graph", return_value=mock_compiled),
        patch("src.engine.pipeline._resolve_run_id_int", new_callable=AsyncMock, return_value=1),
        patch("src.engine.run.update_run_status", new_callable=AsyncMock),
        patch("src.engine.run.finish_run", new_callable=AsyncMock),
        patch("src.engine.pipeline._fire_pipeline_hook", new_callable=AsyncMock),
        patch("src.mcp.manager.MCPManager") as MockMCP,
    ):
        mock_pipeline = MagicMock()
        mock_pipeline.nodes = [MagicMock(name="w", output="out", input=[])]
        mock_load.return_value = mock_pipeline
        MockMCP.return_value = AsyncMock()

        result = await resume_pipeline(
            pipeline_name="test",
            run_id="r1",
            project_id=1,
            feedback=None,
        )

    check("Completed with None feedback", result.status == "completed")
    # Verify Command was called with resume=None
    from langgraph.types import Command
    cmd = mock_compiled.ainvoke.call_args[0][0]
    check("Command resume is None", cmd.resume is None)


asyncio.run(test_resume_no_feedback())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
