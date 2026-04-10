"""build_graph tests: graph construction from PipelineDefinition."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.graph import PipelineState, build_graph
from src.engine.pipeline import (
    NodeDefinition,
    PipelineDefinition,
    RouteDefinition,
)

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


def make_pipeline(nodes: list[NodeDefinition], name: str = "test") -> PipelineDefinition:
    """Helper to build a PipelineDefinition from nodes."""
    output_to_node = {n.output: n.name for n in nodes}
    dependencies: dict[str, set[str]] = {}
    for n in nodes:
        deps = set()
        for inp in n.input:
            if inp in output_to_node:
                deps.add(output_to_node[inp])
        dependencies[n.name] = deps
    return PipelineDefinition(
        name=name,
        description="test pipeline",
        nodes=nodes,
        output_to_node=output_to_node,
        dependencies=dependencies,
    )


abort = asyncio.Event()


# ── 1. Single node graph ────────────────────────────────

print("\n=== 1. Single node graph ===")

single_pipeline = make_pipeline([
    NodeDefinition(name="writer", role="writer", output="draft"),
])

compiled = build_graph(
    single_pipeline,
    run_id="r1",
    run_id_int=1,
    abort_signal=abort,
    permission_mode="normal",
)

# Check the graph was compiled (has ainvoke method)
check("Single node graph compiles", hasattr(compiled, "ainvoke"))

# ── 2. Linear graph (A → B → C) ─────────────────────────

print("\n=== 2. Linear graph ===")

linear_pipeline = make_pipeline([
    NodeDefinition(name="researcher", role="researcher", output="research"),
    NodeDefinition(name="writer", role="writer", output="draft", input=["research"]),
    NodeDefinition(name="reviewer", role="reviewer", output="review", input=["draft"]),
])

compiled2 = build_graph(
    linear_pipeline,
    run_id="r2",
    run_id_int=2,
    abort_signal=abort,
    permission_mode="normal",
)

check("Linear graph compiles", hasattr(compiled2, "ainvoke"))

# ── 3. Fan-out graph (A → B, A → C, B+C → D) ───────────

print("\n=== 3. Fan-out graph ===")

fanout_pipeline = make_pipeline([
    NodeDefinition(name="researcher", role="researcher", output="research"),
    NodeDefinition(name="writer", role="writer", output="draft", input=["research"]),
    NodeDefinition(name="analyst", role="analyst", output="analysis", input=["research"]),
    NodeDefinition(name="editor", role="editor", output="final", input=["draft", "analysis"]),
])

compiled3 = build_graph(
    fanout_pipeline,
    run_id="r3",
    run_id_int=3,
    abort_signal=abort,
    permission_mode="normal",
)

check("Fan-out graph compiles", hasattr(compiled3, "ainvoke"))

# ── 4. Interrupt node split ──────────────────────────────

print("\n=== 4. Interrupt node split ===")

interrupt_pipeline = make_pipeline([
    NodeDefinition(name="writer", role="writer", output="draft"),
    NodeDefinition(name="reviewer", role="reviewer", output="review", input=["draft"], interrupt=True),
])

compiled4 = build_graph(
    interrupt_pipeline,
    run_id="r4",
    run_id_int=4,
    abort_signal=abort,
    permission_mode="normal",
)

check("Interrupt graph compiles", hasattr(compiled4, "ainvoke"))

# Verify the graph has the split nodes
graph_nodes = compiled4.get_graph().nodes
node_names = set(graph_nodes.keys())
check("reviewer_run node exists", "reviewer_run" in node_names)
check("reviewer_interrupt node exists", "reviewer_interrupt" in node_names)
check("writer node exists (no interrupt)", "writer" in node_names)

# ── 5. Conditional routing graph ─────────────────────────

print("\n=== 5. Conditional routing graph ===")

route_pipeline = make_pipeline([
    NodeDefinition(
        name="reviewer", role="reviewer", output="review_result",
        routes=[
            RouteDefinition(target="publish", condition="通过"),
            RouteDefinition(target="revise", is_default=True),
        ],
    ),
    NodeDefinition(name="publish", role="publisher", output="published", input=["review_result"]),
    NodeDefinition(name="revise", role="writer", output="revised", input=["review_result"]),
])

compiled5 = build_graph(
    route_pipeline,
    run_id="r5",
    run_id_int=5,
    abort_signal=abort,
    permission_mode="normal",
)

check("Route graph compiles", hasattr(compiled5, "ainvoke"))

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
