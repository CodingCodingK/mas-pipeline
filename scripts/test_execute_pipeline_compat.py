"""Compatibility test: execute_pipeline with no interrupt behaves same as before refactor."""

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


# ── 1. Linear pipeline (no interrupt) → completed ───────

print("\n=== 1. Linear pipeline (no interrupt) → completed ===")


async def test_linear_no_interrupt():
    """3-node linear pipeline completes without pause."""
    from src.engine.graph import PipelineState, build_graph
    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    nodes = [
        NodeDefinition(name="researcher", role="researcher", output="research"),
        NodeDefinition(name="writer", role="writer", output="draft", input=["research"]),
        NodeDefinition(name="reviewer", role="reviewer", output="review", input=["draft"]),
    ]
    pipeline = PipelineDefinition(
        name="test_linear",
        description="test",
        nodes=nodes,
        output_to_node={"research": "researcher", "draft": "writer", "review": "reviewer"},
        dependencies={"researcher": set(), "writer": {"researcher"}, "reviewer": {"writer"}},
    )

    execution_order: list[str] = []

    async def mock_run(node, task_description, **kwargs):
        execution_order.append(node.name)
        return f"{node.name} output"

    from langgraph.checkpoint.memory import MemorySaver

    with patch("src.engine.pipeline._run_node", side_effect=mock_run):
        compiled = build_graph(
            pipeline,
            run_id="r1",
            run_id_int=1,
            abort_signal=asyncio.Event(),
            permission_mode="normal",
            checkpointer=MemorySaver(),
        )

        config = {"configurable": {"thread_id": "r1"}}
        initial: PipelineState = {
            "user_input": "Write about AI",
            "outputs": {},
            "run_id": "r1",
            "project_id": 1,
            "permission_mode": "normal",
            "error": None,
        }

        result = await compiled.ainvoke(initial, config=config)
        state = await compiled.aget_state(config)

    check("Graph completed", len(state.next) == 0)
    check("All 3 nodes ran", len(execution_order) == 3)
    check("Execution order correct", execution_order == ["researcher", "writer", "reviewer"])
    check("All outputs present", len(result["outputs"]) == 3)
    check("Final output is reviewer's", result["outputs"]["review"] == "reviewer output")
    check("No error", result.get("error") is None)


asyncio.run(test_linear_no_interrupt())


# ── 2. Fan-out pipeline → parallel execution ────────────

print("\n=== 2. Fan-out pipeline → parallel ===")


async def test_fanout():
    """A → B+C (parallel) → D pattern."""
    from src.engine.graph import PipelineState, build_graph
    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    nodes = [
        NodeDefinition(name="source", role="researcher", output="data"),
        NodeDefinition(name="branch_a", role="writer", output="a_out", input=["data"]),
        NodeDefinition(name="branch_b", role="analyst", output="b_out", input=["data"]),
        NodeDefinition(name="merge", role="editor", output="final", input=["a_out", "b_out"]),
    ]
    pipeline = PipelineDefinition(
        name="test_fanout",
        description="test",
        nodes=nodes,
        output_to_node={"data": "source", "a_out": "branch_a", "b_out": "branch_b", "final": "merge"},
        dependencies={
            "source": set(),
            "branch_a": {"source"},
            "branch_b": {"source"},
            "merge": {"branch_a", "branch_b"},
        },
    )

    ran: list[str] = []

    async def mock_run(node, task_description, **kwargs):
        ran.append(node.name)
        return f"{node.name} output"

    from langgraph.checkpoint.memory import MemorySaver

    with patch("src.engine.pipeline._run_node", side_effect=mock_run):
        compiled = build_graph(
            pipeline,
            run_id="r2",
            run_id_int=2,
            abort_signal=asyncio.Event(),
            permission_mode="normal",
            checkpointer=MemorySaver(),
        )

        config = {"configurable": {"thread_id": "r2"}}
        initial: PipelineState = {
            "user_input": "Analyze data",
            "outputs": {},
            "run_id": "r2",
            "project_id": 1,
            "permission_mode": "normal",
            "error": None,
        }

        result = await compiled.ainvoke(initial, config=config)

    check("All 4 nodes ran", len(ran) == 4)
    check("Source ran first", ran[0] == "source")
    check("Merge ran last", ran[-1] == "merge")
    check("Both branches ran", "branch_a" in ran and "branch_b" in ran)
    check("All 4 outputs present", len(result["outputs"]) == 4)
    check("Merge output correct", result["outputs"]["final"] == "merge output")


asyncio.run(test_fanout())


# ── 3. Node failure → error, downstream skipped ─────────

print("\n=== 3. Node failure → error ===")


async def test_node_failure():
    """Middle node fails → error captured, downstream not executed."""
    from src.engine.graph import PipelineState, build_graph
    from src.engine.pipeline import NodeDefinition, PipelineDefinition

    nodes = [
        NodeDefinition(name="good", role="researcher", output="data"),
        NodeDefinition(name="bad", role="writer", output="draft", input=["data"]),
        NodeDefinition(name="after_bad", role="reviewer", output="review", input=["draft"]),
    ]
    pipeline = PipelineDefinition(
        name="test_fail",
        description="test",
        nodes=nodes,
        output_to_node={"data": "good", "draft": "bad", "review": "after_bad"},
        dependencies={"good": set(), "bad": {"good"}, "after_bad": {"bad"}},
    )

    ran: list[str] = []

    async def mock_run(node, task_description, **kwargs):
        ran.append(node.name)
        if node.name == "bad":
            raise RuntimeError("LLM crashed")
        return f"{node.name} output"

    from langgraph.checkpoint.memory import MemorySaver

    with patch("src.engine.pipeline._run_node", side_effect=mock_run):
        compiled = build_graph(
            pipeline,
            run_id="r3",
            run_id_int=3,
            abort_signal=asyncio.Event(),
            permission_mode="normal",
            checkpointer=MemorySaver(),
        )

        config = {"configurable": {"thread_id": "r3"}}
        initial: PipelineState = {
            "user_input": "test",
            "outputs": {},
            "run_id": "r3",
            "project_id": 1,
            "permission_mode": "normal",
            "error": None,
        }

        result = await compiled.ainvoke(initial, config=config)

    check("Good node ran", "good" in ran)
    check("Bad node ran", "bad" in ran)
    check("After_bad NOT ran (skipped)", "after_bad" not in ran)
    check("Error captured", result.get("error") is not None)
    check("Error mentions crash", "LLM crashed" in result["error"])
    check("Good node output preserved", result["outputs"].get("data") == "good output")


asyncio.run(test_node_failure())


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
