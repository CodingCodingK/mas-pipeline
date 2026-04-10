"""Integration tests: full pipeline execute → interrupt → resume → complete flow."""

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


def _patch_infra():
    """Common patches for DB/MCP/checkpointer infrastructure."""
    mock_cp = AsyncMock()
    mock_cp.aget = AsyncMock(return_value={"exists": True})

    return {
        "get_checkpointer": patch(
            "src.engine.pipeline.get_checkpointer",
            new_callable=AsyncMock,
            return_value=mock_cp,
        ),
        "resolve_run_id": patch(
            "src.engine.pipeline._resolve_run_id_int",
            new_callable=AsyncMock,
            return_value=1,
        ),
        "update_status": patch(
            "src.engine.pipeline.update_run_status",
            new_callable=AsyncMock,
        ),
        "finish_run": patch(
            "src.engine.pipeline.finish_run",
            new_callable=AsyncMock,
        ),
        "fire_hook": patch(
            "src.engine.pipeline._fire_pipeline_hook",
            new_callable=AsyncMock,
        ),
        "mcp_manager": patch("src.mcp.manager.MCPManager"),
        "get_settings": patch("src.engine.pipeline.get_settings"),
    }


# ── 1. Full pipeline: execute → interrupt → resume → complete ──

print("\n=== 1. Execute → interrupt → resume → complete ===")


async def test_full_interrupt_flow():
    """Mock _run_node to simulate: writer runs → reviewer pauses → resume → complete."""
    from src.engine.graph import PipelineState, build_graph
    from src.engine.pipeline import (
        NodeDefinition,
        PipelineDefinition,
        _find_terminal_outputs,
    )

    # Build pipeline: writer → reviewer(interrupt)
    nodes = [
        NodeDefinition(name="writer", role="writer", output="draft"),
        NodeDefinition(name="reviewer", role="reviewer", output="review", input=["draft"], interrupt=True),
    ]
    pipeline = PipelineDefinition(
        name="test_interrupt",
        description="test",
        nodes=nodes,
        output_to_node={"draft": "writer", "review": "reviewer"},
        dependencies={"writer": set(), "reviewer": {"writer"}},
    )

    abort = asyncio.Event()

    # Track _run_node calls
    run_calls: list[str] = []

    async def mock_run_node(node, task_description, **kwargs):
        run_calls.append(node.name)
        if node.name == "writer":
            return "This is the draft content."
        elif node.name == "reviewer":
            return "Review: 通过"
        return "(no output)"

    # Use in-memory checkpointer (no DB needed)
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()

    with patch("src.engine.pipeline._run_node", side_effect=mock_run_node):
        # Build graph
        compiled = build_graph(
            pipeline,
            run_id="r1",
            run_id_int=1,
            abort_signal=abort,
            permission_mode="normal",
            checkpointer=checkpointer,
        )

        initial_state: PipelineState = {
            "user_input": "Write about AI",
            "outputs": {},
            "run_id": "r1",
            "project_id": 1,
            "permission_mode": "normal",
            "error": None,
        }

        config = {"configurable": {"thread_id": "r1"}}

        # Execute — should pause at reviewer_interrupt
        result1 = await compiled.ainvoke(initial_state, config=config)

        # Check graph state
        graph_state = await compiled.aget_state(config)
        check("Graph paused (has next)", len(graph_state.next) > 0)
        check("Paused at reviewer_interrupt", "reviewer_interrupt" in graph_state.next)

        # Writer ran, reviewer ran, but interrupt paused before downstream
        check("Writer ran", "writer" in run_calls)
        check("Reviewer ran", "reviewer" in run_calls)
        check("Draft output captured", result1.get("outputs", {}).get("draft") == "This is the draft content.")
        check("Review output captured", result1.get("outputs", {}).get("review") == "Review: 通过")

        # Resume
        from langgraph.types import Command
        result2 = await compiled.ainvoke(Command(resume="approved"), config=config)

        # After resume, graph should complete
        graph_state2 = await compiled.aget_state(config)
        check("Graph completed (no next)", len(graph_state2.next) == 0)

        # Verify no re-execution of _run_node during resume
        check("No extra _run_node calls after resume", len(run_calls) == 2)

        # Outputs preserved
        final_outputs = result2.get("outputs", {})
        check("Final outputs has draft", "draft" in final_outputs)
        check("Final outputs has review", "review" in final_outputs)


asyncio.run(test_full_interrupt_flow())


# ── 2. Multi-node pipeline: interrupt mid-chain ─────────

print("\n=== 2. Multi-node: A → B(interrupt) → C ===")


async def test_multi_node_interrupt():
    """Pipeline: researcher → editor(interrupt) → publisher. Verify outputs pass through."""
    from src.engine.graph import PipelineState, build_graph
    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    nodes = [
        NodeDefinition(name="researcher", role="researcher", output="research"),
        NodeDefinition(name="editor", role="editor", output="edited", input=["research"], interrupt=True),
        NodeDefinition(name="publisher", role="publisher", output="published", input=["edited"]),
    ]
    pipeline = PipelineDefinition(
        name="test_multi",
        description="test",
        nodes=nodes,
        output_to_node={"research": "researcher", "edited": "editor", "published": "publisher"},
        dependencies={"researcher": set(), "editor": {"researcher"}, "publisher": {"editor"}},
    )

    run_calls: list[str] = []

    async def mock_run(node, task_description, **kwargs):
        run_calls.append(node.name)
        return f"{node.name} output"

    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()

    with patch("src.engine.pipeline._run_node", side_effect=mock_run):
        compiled = build_graph(
            pipeline,
            run_id="r2",
            run_id_int=2,
            abort_signal=asyncio.Event(),
            permission_mode="normal",
            checkpointer=checkpointer,
        )

        config = {"configurable": {"thread_id": "r2"}}
        initial: PipelineState = {
            "user_input": "Research AI",
            "outputs": {},
            "run_id": "r2",
            "project_id": 1,
            "permission_mode": "normal",
            "error": None,
        }

        # Execute — should pause at editor_interrupt
        result1 = await compiled.ainvoke(initial, config=config)
        state1 = await compiled.aget_state(config)

        check("Paused at editor_interrupt", "editor_interrupt" in state1.next)
        check("Researcher ran", "researcher" in run_calls)
        check("Editor ran", "editor" in run_calls)
        check("Publisher NOT yet", "publisher" not in run_calls)

        # Resume
        from langgraph.types import Command
        result2 = await compiled.ainvoke(Command(resume="ok"), config=config)
        state2 = await compiled.aget_state(config)

        check("Graph completed after resume", len(state2.next) == 0)
        check("Publisher ran after resume", "publisher" in run_calls)
        check("Total _run_node calls = 3", len(run_calls) == 3)

        # Verify upstream outputs pass through to downstream
        final = result2.get("outputs", {})
        check("Research output preserved", final.get("research") == "researcher output")
        check("Edited output preserved", final.get("edited") == "editor output")
        check("Published output present", final.get("published") == "publisher output")


asyncio.run(test_multi_node_interrupt())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
