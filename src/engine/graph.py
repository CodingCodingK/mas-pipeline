"""LangGraph StateGraph builder for pipeline execution.

Converts a PipelineDefinition into a compiled LangGraph StateGraph.
Each YAML node becomes one or two graph nodes (interrupt nodes are split).
Edges are derived from input/output dependencies.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.engine.pipeline import NodeDefinition, PipelineDefinition

logger = logging.getLogger(__name__)


# ── State ────────────────────────────────────────────────


def _merge_dicts(left: dict[str, str], right: dict[str, str]) -> dict[str, str]:
    """Merge reducer for outputs dict — prevents parallel nodes overwriting each other."""
    merged = left.copy()
    merged.update(right)
    return merged


def _first_error(left: str | None, right: str | None) -> str | None:
    """Error reducer: keep the first error seen (prevents parallel-failure crash)."""
    return left if left is not None else right


class PipelineState(TypedDict):
    user_input: str
    outputs: Annotated[dict[str, str], _merge_dicts]
    run_id: str
    project_id: int
    permission_mode: str
    error: Annotated[str | None, _first_error]


# ── Node function factories ──────────────────────────────


def _make_node_fn(
    node: NodeDefinition,
    *,
    run_id: str,
    run_id_int: int,
    abort_signal: asyncio.Event,
    permission_mode: object,
    mcp_manager: object | None,
) -> Any:
    """Create a graph node function that wraps _run_node for this pipeline node.

    Non-serializable objects (abort_signal, mcp_manager, etc.) are captured
    via closure — they never enter PipelineState.
    """

    async def node_fn(state: PipelineState) -> dict[str, Any]:
        # If a previous node already failed, short-circuit
        if state.get("error"):
            return {}

        # Fan-in guard: wait until all declared upstream inputs are ready.
        # LangGraph conditional_edges from multiple parents trigger independently,
        # so this function may be invoked before all parents have written their
        # outputs. Skip (no state update) until inputs are complete.
        current_outputs = state.get("outputs") or {}
        for inp in node.input:
            if inp not in current_outputs:
                return {}

        # Also skip if we already produced our output (re-trigger from late parent)
        if node.output in current_outputs:
            return {}

        from src.engine.pipeline import _build_task_description, _run_node
        from src.engine.run import emit_pipeline_event

        # Build task description from upstream outputs
        task_desc = _build_task_description(node, state["outputs"], state["user_input"])

        emit_pipeline_event(state["run_id"], {
            "type": "node_start",
            "node": node.name,
            "role": node.role,
            "output_name": node.output,
        })

        try:
            output = await _run_node(
                node=node,
                task_description=task_desc,
                project_id=state["project_id"],
                run_id=state["run_id"],
                run_id_int=run_id_int,
                abort_signal=abort_signal,
                permission_mode=permission_mode,
                mcp_manager=mcp_manager,
            )
            emit_pipeline_event(state["run_id"], {
                "type": "node_end",
                "node": node.name,
                "output_name": node.output,
                "output_length": len(output) if output else 0,
                "output_preview": (output[:200] if output else ""),
            })
            return {"outputs": {node.output: output}}
        except Exception as exc:
            logger.error("Node '%s' failed: %s", node.name, exc)
            emit_pipeline_event(state["run_id"], {
                "type": "node_failed",
                "node": node.name,
                "error": str(exc),
            })
            return {"error": str(exc)}

    node_fn.__name__ = node.name
    return node_fn


def _make_interrupt_fn(node: NodeDefinition) -> Any:
    """Create a lightweight interrupt node that pauses the graph.

    This is the second half of an interrupt-enabled node.
    The expensive agent work is done in the _run node; this node
    just calls interrupt() so resume doesn't re-run the agent.
    """

    async def interrupt_fn(state: PipelineState) -> dict[str, Any]:
        if state.get("error"):
            return {}

        output_content = state["outputs"].get(node.output, "")
        # Pause execution — resume will re-enter here
        feedback = interrupt({
            "node": node.name,
            "output": output_content,
        })
        # feedback from resume is available but we don't modify state with it
        logger.info("Node '%s' resumed with feedback: %s", node.name, feedback)
        return {}

    interrupt_fn.__name__ = f"{node.name}_interrupt"
    return interrupt_fn


# ── Graph construction ───────────────────────────────────


def build_graph(
    pipeline_def: PipelineDefinition,
    *,
    run_id: str,
    run_id_int: int,
    abort_signal: asyncio.Event,
    permission_mode: object,
    mcp_manager: object | None = None,
    checkpointer: object | None = None,
) -> Any:
    """Build and compile a LangGraph StateGraph from a PipelineDefinition.

    Returns a compiled graph ready for .ainvoke().
    """
    graph = StateGraph(PipelineState)

    node_by_name: dict[str, NodeDefinition] = {n.name: n for n in pipeline_def.nodes}

    # Track the "exit" LangGraph node name for each pipeline node
    # (for interrupt nodes, the exit is {name}_interrupt; otherwise just {name})
    exit_node: dict[str, str] = {}

    # ── Add nodes ────────────────────────────────────────
    for node in pipeline_def.nodes:
        fn = _make_node_fn(
            node,
            run_id=run_id,
            run_id_int=run_id_int,
            abort_signal=abort_signal,
            permission_mode=permission_mode,
            mcp_manager=mcp_manager,
        )

        if node.interrupt:
            # Split into run + interrupt nodes
            run_name = f"{node.name}_run"
            interrupt_name = f"{node.name}_interrupt"
            fn.__name__ = run_name

            graph.add_node(run_name, fn)
            graph.add_node(interrupt_name, _make_interrupt_fn(node))
            graph.add_edge(run_name, interrupt_name)
            exit_node[node.name] = interrupt_name
        else:
            graph.add_node(node.name, fn)
            exit_node[node.name] = node.name

    # ── Determine entry and terminal nodes ───────────────
    # Entry nodes: no input dependencies
    entry_nodes = [n.name for n in pipeline_def.nodes if not n.input]

    # Terminal nodes: no other node depends on their output
    all_inputs: set[str] = set()
    for n in pipeline_def.nodes:
        all_inputs.update(n.input)
    terminal_nodes = [n.name for n in pipeline_def.nodes if n.output not in all_inputs]

    # ── Add START edges ──────────────────────────────────
    for name in entry_nodes:
        node = node_by_name[name]
        entry_lg_node = f"{name}_run" if node.interrupt else name
        graph.add_edge(START, entry_lg_node)

    # ── Add inter-node edges ─────────────────────────────
    # Build: output_name → list of downstream pipeline node names
    output_consumers: dict[str, list[str]] = {}
    for node in pipeline_def.nodes:
        for inp in node.input:
            output_consumers.setdefault(inp, []).append(node.name)

    # For each node, determine its downstream connections
    for node in pipeline_def.nodes:
        downstream_names = output_consumers.get(node.output, [])
        src_lg_node = exit_node[node.name]

        if node.routes:
            # Conditional routing — build routing function
            _add_route_edges(graph, node, src_lg_node, node_by_name, exit_node, terminal_nodes)
        elif downstream_names:
            # Normal edges with error check
            _add_error_checked_edges(
                graph, src_lg_node, node.name, downstream_names, node_by_name, exit_node, terminal_nodes
            )
        else:
            # Terminal node — add error-checked edge to END
            _add_conditional_end(graph, src_lg_node)

    return graph.compile(checkpointer=checkpointer)


def _add_conditional_end(graph: StateGraph, src_node: str) -> None:
    """Add a conditional edge: error → END, no error → END (terminal node)."""
    # Terminal nodes always go to END, but we still add as normal edge
    graph.add_edge(src_node, END)


def _add_error_checked_edges(
    graph: StateGraph,
    src_lg_node: str,
    src_pipeline_name: str,
    downstream_names: list[str],
    node_by_name: dict[str, NodeDefinition],
    exit_node: dict[str, str],
    terminal_nodes: list[str],
) -> None:
    """Add conditional edges: error → END, no error → downstream nodes."""

    # Build target mapping for the conditional edge
    targets: dict[str, str] = {}
    for ds_name in downstream_names:
        ds_node = node_by_name[ds_name]
        ds_lg_node = f"{ds_name}_run" if ds_node.interrupt else ds_name
        targets[ds_name] = ds_lg_node

    def route_fn(state: PipelineState) -> list[str] | str:
        if state.get("error"):
            return END
        # Fan-out to all downstream nodes
        if len(targets) == 1:
            return next(iter(targets.values()))
        return list(targets.values())

    route_fn.__name__ = f"after_{src_pipeline_name}"

    path_map: dict[str, str] = {END: END}
    for ds_name, lg_name in targets.items():
        path_map[lg_name] = lg_name

    graph.add_conditional_edges(src_lg_node, route_fn, path_map)


def _add_route_edges(
    graph: StateGraph,
    node: NodeDefinition,
    src_lg_node: str,
    node_by_name: dict[str, NodeDefinition],
    exit_node: dict[str, str],
    terminal_nodes: list[str],
) -> None:
    """Add conditional routing edges based on output content substring matching.

    Error check takes priority: if state["error"] is set, route to END.
    Otherwise, check each route condition against the node's output.
    """
    # Collect route targets
    conditions: list[tuple[str, str]] = []  # (substring, target_pipeline_name)
    default_target: str | None = None

    for route in node.routes:
        if route.is_default:
            default_target = route.target
        else:
            assert route.condition is not None
            conditions.append((route.condition, route.target))

    # Build path_map: all possible destinations
    all_targets: set[str] = set()
    for _, t in conditions:
        all_targets.add(t)
    if default_target:
        all_targets.add(default_target)

    path_map: dict[str, str] = {END: END}
    for t_name in all_targets:
        t_node = node_by_name[t_name]
        lg_name = f"{t_name}_run" if t_node.interrupt else t_name
        path_map[t_name] = lg_name

    output_name = node.output

    def route_fn(state: PipelineState) -> str:
        # Error takes priority
        if state.get("error"):
            return END

        content = state["outputs"].get(output_name, "")
        for condition_str, target_name in conditions:
            if condition_str in content:
                return target_name
        if default_target:
            return default_target
        return END

    route_fn.__name__ = f"route_{node.name}"

    graph.add_conditional_edges(src_lg_node, route_fn, path_map)
