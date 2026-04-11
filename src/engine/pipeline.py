"""Pipeline engine: YAML definition loading, dependency inference, and reactive execution."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.storage import resolve_pipeline_file

logger = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────


@dataclass
class RouteDefinition:
    target: str
    condition: str | None = None            # substring match on output content
    is_default: bool = False


@dataclass
class NodeDefinition:
    name: str
    role: str
    output: str
    input: list[str] = field(default_factory=list)
    interrupt: bool = False
    routes: list[RouteDefinition] = field(default_factory=list)


@dataclass
class PipelineDefinition:
    name: str
    description: str
    nodes: list[NodeDefinition]
    output_to_node: dict[str, str]          # output_name → node_name
    dependencies: dict[str, set[str]]       # node_name → set of dependency node_names


# ── Loading ───────────────────────────────────────────────


def load_pipeline(yaml_path: str) -> PipelineDefinition:
    """Load and validate a pipeline definition from a YAML file."""
    path = Path(yaml_path)
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline YAML not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "pipeline" not in raw:
        raise ValueError("Pipeline YAML must contain a 'pipeline' field")

    nodes_raw = raw.get("nodes")
    if not nodes_raw or not isinstance(nodes_raw, list):
        raise ValueError("Pipeline YAML must contain a non-empty 'nodes' list")

    nodes = [
        NodeDefinition(
            name=n["name"],
            role=n["role"],
            output=n["output"],
            input=n.get("input", []),
            interrupt=n.get("interrupt", False),
            routes=_parse_routes(n.get("routes", []), n["name"]),
        )
        for n in nodes_raw
    ]

    # Build output → node mapping
    output_to_node: dict[str, str] = {}
    for node in nodes:
        if node.output in output_to_node:
            raise ValueError(
                f"Duplicate output '{node.output}': "
                f"nodes '{output_to_node[node.output]}' and '{node.name}'"
            )
        output_to_node[node.output] = node.name

    # Build node name set for route validation
    node_names = {n.name for n in nodes}

    # Validate routes
    for node in nodes:
        _validate_routes(node, node_names)

    # Infer dependencies
    dependencies: dict[str, set[str]] = {}
    for node in nodes:
        deps: set[str] = set()
        for input_name in node.input:
            if input_name not in output_to_node:
                raise ValueError(
                    f"Node '{node.name}' references unknown input '{input_name}'"
                )
            deps.add(output_to_node[input_name])
        dependencies[node.name] = deps

    # Cycle detection (Kahn's algorithm)
    _check_no_cycles(nodes, dependencies)

    return PipelineDefinition(
        name=raw["pipeline"],
        description=raw.get("description", ""),
        nodes=nodes,
        output_to_node=output_to_node,
        dependencies=dependencies,
    )


def _parse_routes(routes_raw: list, node_name: str) -> list[RouteDefinition]:
    """Parse route definitions from YAML."""
    routes: list[RouteDefinition] = []
    for r in routes_raw:
        if "default" in r:
            routes.append(RouteDefinition(target=r["default"], is_default=True))
        elif "condition" in r and "target" in r:
            routes.append(RouteDefinition(target=r["target"], condition=r["condition"]))
        else:
            raise ValueError(
                f"Node '{node_name}': route must have 'condition'+'target' or 'default'"
            )
    return routes


def _validate_routes(node: NodeDefinition, node_names: set[str]) -> None:
    """Validate route definitions for a node."""
    if not node.routes:
        return
    default_count = sum(1 for r in node.routes if r.is_default)
    if default_count > 1:
        raise ValueError(f"Node '{node.name}': at most one default route allowed")
    has_default = default_count == 1
    has_conditions = any(r.condition for r in node.routes)
    if not has_default and has_conditions:
        raise ValueError(
            f"Node '{node.name}': routes with conditions must have a default route"
        )
    for r in node.routes:
        if r.target not in node_names:
            raise ValueError(
                f"Node '{node.name}': route target '{r.target}' is not a valid node"
            )


def _check_no_cycles(
    nodes: list[NodeDefinition],
    dependencies: dict[str, set[str]],
) -> None:
    """Raise ValueError if the dependency graph contains a cycle."""
    in_degree: dict[str, int] = {n.name: 0 for n in nodes}
    reverse: dict[str, list[str]] = defaultdict(list)

    for node_name, deps in dependencies.items():
        in_degree[node_name] = len(deps)
        for dep in deps:
            reverse[dep].append(node_name)

    queue = [name for name, deg in in_degree.items() if deg == 0]
    visited = 0

    while queue:
        current = queue.pop()
        visited += 1
        for downstream in reverse[current]:
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)

    if visited < len(nodes):
        remaining = [n for n, d in in_degree.items() if d > 0]
        raise ValueError(f"Pipeline has a cycle involving nodes: {remaining}")


# ── Result ────────────────────────────────────────────────


@dataclass
class PipelineResult:
    run_id: str
    status: str                             # 'completed' / 'failed' / 'paused'
    outputs: dict[str, str]                 # output_name → content
    final_output: str
    failed_node: str | None = None
    error: str | None = None
    paused_at: str | None = None            # node name where pipeline paused


# ── Execution ─────────────────────────────────────────────


async def _fire_pipeline_hook(hook_runner: object | None, event_name: str, payload: dict) -> None:
    """Fire a pipeline lifecycle hook if hook_runner is available."""
    if not hook_runner:
        return
    try:
        from src.hooks.types import HookEvent, HookEventType
        event = HookEvent(event_type=HookEventType(event_name), payload=payload)
        await hook_runner.run(event)  # type: ignore[union-attr]
    except Exception:
        logger.warning("Pipeline hook %s failed (non-blocking)", event_name, exc_info=True)


async def execute_pipeline(
    pipeline_name: str,
    run_id: str,
    project_id: int,
    user_input: str,
    hook_runner: object | None = None,
    permission_mode: object | None = None,
) -> PipelineResult:
    """Execute a pipeline: load YAML, build LangGraph, invoke.

    The caller must have already created a WorkflowRun with this run_id.
    Creates an MCPManager from settings, starts MCP servers before graph
    execution, and shuts them down when the pipeline completes.
    """
    from src.db import get_checkpointer
    from src.engine.graph import PipelineState, build_graph
    from src.engine.run import (
        RunStatus,
        emit_pipeline_event,
        finish_run,
        update_run_status,
    )
    from src.mcp.manager import MCPManager
    from src.permissions.types import PermissionMode
    from src.project.config import get_settings
    from src.telemetry import current_project_id, current_run_id, get_collector

    if permission_mode is None:
        permission_mode = PermissionMode.NORMAL

    # Load pipeline via layered resolver (project override wins over global)
    yaml_path = str(resolve_pipeline_file(pipeline_name, project_id))
    pipeline = load_pipeline(yaml_path)

    # Start MCP servers
    mcp_manager = MCPManager()
    settings = get_settings()
    if settings.mcp_servers:
        await mcp_manager.start(settings.mcp_servers)

    collector = get_collector()
    run_id_token = current_run_id.set(run_id)
    project_id_token = current_project_id.set(project_id)
    try:
        collector.record_pipeline_event(
            pipeline_event_type="pipeline_start",
            pipeline_name=pipeline_name,
        )
        # Fire PipelineStart hook
        await _fire_pipeline_hook(hook_runner, "pipeline_start", {
            "pipeline_name": pipeline_name,
            "run_id": run_id,
            "project_id": project_id,
            "user_input": user_input,
        })
        emit_pipeline_event(run_id, {
            "type": "pipeline_start",
            "pipeline": pipeline_name,
            "node_count": len(pipeline.nodes),
        })

        # Transition run: pending → running
        await update_run_status(run_id, RunStatus.RUNNING)

        # Resolve run_id str → workflow_runs.id for task creation
        run_id_int = await _resolve_run_id_int(run_id)

        # Shared abort signal — register so REST cancel endpoint can flip it.
        from src.engine.run import register_abort_signal, unregister_abort_signal
        abort_signal = asyncio.Event()
        register_abort_signal(run_id, abort_signal)

        # Build and compile the LangGraph
        checkpointer = await get_checkpointer()
        compiled = build_graph(
            pipeline,
            run_id=run_id,
            run_id_int=run_id_int,
            abort_signal=abort_signal,
            permission_mode=permission_mode,
            mcp_manager=mcp_manager,
            checkpointer=checkpointer,
        )

        # Initial state
        initial_state: PipelineState = {
            "user_input": user_input,
            "outputs": {},
            "run_id": run_id,
            "project_id": project_id,
            "permission_mode": str(permission_mode.value if hasattr(permission_mode, "value") else permission_mode),
            "error": None,
        }

        # Run the graph
        config = {"configurable": {"thread_id": run_id}}
        try:
            final_state = await compiled.ainvoke(initial_state, config=config)
        except Exception as exc:
            logger.exception("Pipeline graph execution failed")
            await finish_run(
                run_id,
                RunStatus.FAILED,
                result_payload={
                    "final_output": "",
                    "outputs": {},
                    "failed_node": None,
                    "error": str(exc),
                    "paused_at": None,
                },
            )

            await _fire_pipeline_hook(hook_runner, "pipeline_end", {
                "pipeline_name": pipeline_name,
                "run_id": run_id,
                "status": "failed",
                "error": str(exc),
            })
            emit_pipeline_event(run_id, {
                "type": "pipeline_end",
                "status": "failed",
                "error": str(exc),
            })

            return PipelineResult(
                run_id=run_id,
                status="failed",
                outputs={},
                final_output="",
                error=str(exc),
            )

        # Check if the graph was interrupted (paused)
        graph_state = await compiled.aget_state(config)
        if graph_state.next:
            # Graph paused at an interrupt node
            paused_node = graph_state.next[0]
            # Strip _interrupt suffix to get the original node name
            paused_at = paused_node.replace("_interrupt", "")
            await update_run_status(
                run_id,
                RunStatus.PAUSED,
                result_payload={
                    "final_output": "",
                    "outputs": final_state.get("outputs", {}),
                    "failed_node": None,
                    "error": None,
                    "paused_at": paused_at,
                },
            )

            await _fire_pipeline_hook(hook_runner, "pipeline_end", {
                "pipeline_name": pipeline_name,
                "run_id": run_id,
                "status": "paused",
                "paused_at": paused_at,
            })
            emit_pipeline_event(run_id, {
                "type": "pipeline_paused",
                "paused_at": paused_at,
            })

            return PipelineResult(
                run_id=run_id,
                status="paused",
                outputs=final_state.get("outputs", {}),
                final_output="",
                paused_at=paused_at,
            )

        # Determine final status from state
        node_outputs = final_state.get("outputs", {})
        error = final_state.get("error")

        # Find terminal node output
        terminal_outputs = _find_terminal_outputs(pipeline)
        final_output = ""
        for out_name in terminal_outputs:
            if out_name in node_outputs:
                final_output = node_outputs[out_name]
                break

        result_payload = {
            "final_output": final_output,
            "outputs": node_outputs,
            "failed_node": None,
            "error": error,
            "paused_at": None,
        }

        if error:
            status = "failed"
            await finish_run(run_id, RunStatus.FAILED, result_payload=result_payload)
        else:
            status = "completed"
            await finish_run(run_id, RunStatus.COMPLETED, result_payload=result_payload)

        # Fire PipelineEnd hook
        await _fire_pipeline_hook(hook_runner, "pipeline_end", {
            "pipeline_name": pipeline_name,
            "run_id": run_id,
            "status": status,
            "error": error,
        })
        emit_pipeline_event(run_id, {
            "type": "pipeline_end",
            "status": status,
            "error": error,
        })

        return PipelineResult(
            run_id=run_id,
            status=status,
            outputs=node_outputs,
            final_output=final_output,
            error=error,
        )

    finally:
        collector.record_pipeline_event(
            pipeline_event_type="pipeline_end",
            pipeline_name=pipeline_name,
        )
        current_run_id.reset(run_id_token)
        current_project_id.reset(project_id_token)
        await mcp_manager.shutdown()
        unregister_abort_signal(run_id)


# ── Resume & status ──────────────────────────────────────


async def resume_pipeline(
    pipeline_name: str,
    run_id: str,
    project_id: int,
    feedback: str | None = None,
    hook_runner: object | None = None,
    permission_mode: object | None = None,
) -> PipelineResult:
    """Resume a paused pipeline from its checkpoint.

    Rebuilds the graph (node functions need fresh closures),
    then invokes with Command(resume=feedback).
    """
    from langgraph.types import Command

    from src.db import get_checkpointer
    from src.engine.graph import build_graph
    from src.engine.run import RunStatus, finish_run, update_run_status
    from src.mcp.manager import MCPManager
    from src.permissions.types import PermissionMode
    from src.project.config import get_settings
    from src.telemetry import current_project_id, current_run_id, get_collector

    if permission_mode is None:
        permission_mode = PermissionMode.NORMAL

    # Load pipeline definition (layered resolver)
    yaml_path = str(resolve_pipeline_file(pipeline_name, project_id))
    pipeline = load_pipeline(yaml_path)

    # Verify checkpoint exists
    checkpointer = await get_checkpointer()
    config = {"configurable": {"thread_id": run_id}}
    checkpoint = await checkpointer.aget(config)
    if checkpoint is None:
        raise ValueError(f"No checkpoint found for run_id='{run_id}'")

    # Start MCP servers
    mcp_manager = MCPManager()
    settings = get_settings()
    if settings.mcp_servers:
        await mcp_manager.start(settings.mcp_servers)

    collector = get_collector()
    run_id_token = current_run_id.set(run_id)
    project_id_token = current_project_id.set(project_id)
    try:
        collector.record_pipeline_event(
            pipeline_event_type="pipeline_resumed",
            pipeline_name=pipeline_name,
        )
        run_id_int = await _resolve_run_id_int(run_id)
        abort_signal = asyncio.Event()

        # Transition: paused → running
        await update_run_status(run_id, RunStatus.RUNNING)

        # Rebuild graph with fresh closures
        compiled = build_graph(
            pipeline,
            run_id=run_id,
            run_id_int=run_id_int,
            abort_signal=abort_signal,
            permission_mode=permission_mode,
            mcp_manager=mcp_manager,
            checkpointer=checkpointer,
        )

        # Resume from checkpoint
        try:
            final_state = await compiled.ainvoke(
                Command(resume=feedback), config=config
            )
        except Exception as exc:
            logger.exception("Pipeline resume failed")
            await finish_run(
                run_id,
                RunStatus.FAILED,
                result_payload={
                    "final_output": "",
                    "outputs": {},
                    "failed_node": None,
                    "error": str(exc),
                    "paused_at": None,
                },
            )
            return PipelineResult(
                run_id=run_id,
                status="failed",
                outputs={},
                final_output="",
                error=str(exc),
            )

        # Check if paused again at another interrupt
        graph_state = await compiled.aget_state(config)
        if graph_state.next:
            paused_node = graph_state.next[0]
            paused_at = paused_node.replace("_interrupt", "")
            await update_run_status(
                run_id,
                RunStatus.PAUSED,
                result_payload={
                    "final_output": "",
                    "outputs": final_state.get("outputs", {}),
                    "failed_node": None,
                    "error": None,
                    "paused_at": paused_at,
                },
            )

            await _fire_pipeline_hook(hook_runner, "pipeline_end", {
                "pipeline_name": pipeline_name,
                "run_id": run_id,
                "status": "paused",
                "paused_at": paused_at,
            })

            return PipelineResult(
                run_id=run_id,
                status="paused",
                outputs=final_state.get("outputs", {}),
                final_output="",
                paused_at=paused_at,
            )

        # Completed or failed
        node_outputs = final_state.get("outputs", {})
        error = final_state.get("error")

        terminal_outputs = _find_terminal_outputs(pipeline)
        final_output = ""
        for out_name in terminal_outputs:
            if out_name in node_outputs:
                final_output = node_outputs[out_name]
                break

        result_payload = {
            "final_output": final_output,
            "outputs": node_outputs,
            "failed_node": None,
            "error": error,
            "paused_at": None,
        }

        if error:
            status = "failed"
            await finish_run(run_id, RunStatus.FAILED, result_payload=result_payload)
        else:
            status = "completed"
            await finish_run(run_id, RunStatus.COMPLETED, result_payload=result_payload)

        await _fire_pipeline_hook(hook_runner, "pipeline_end", {
            "pipeline_name": pipeline_name,
            "run_id": run_id,
            "status": status,
            "error": error,
        })

        return PipelineResult(
            run_id=run_id,
            status=status,
            outputs=node_outputs,
            final_output=final_output,
            error=error,
        )

    finally:
        collector.record_pipeline_event(
            pipeline_event_type="pipeline_end",
            pipeline_name=pipeline_name,
        )
        current_run_id.reset(run_id_token)
        current_project_id.reset(project_id_token)
        await mcp_manager.shutdown()


async def get_pipeline_status(run_id: str) -> dict:
    """Query the current status of a pipeline run.

    Returns:
        {"status": "running"|"paused"|"completed"|"failed",
         "paused_at": "<node_name>" | None}
    """
    from src.engine.run import get_run

    run = await get_run(run_id)
    if run is None:
        raise ValueError(f"WorkflowRun with run_id='{run_id}' not found")

    result: dict = {"status": run.status, "paused_at": None}

    if run.status == "paused":
        # Check checkpoint to find which node is paused
        from src.db import get_checkpointer
        checkpointer = await get_checkpointer()
        config = {"configurable": {"thread_id": run_id}}

        # We need the compiled graph to call aget_state, but we can read
        # the checkpoint directly for the pending nodes info
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple and checkpoint_tuple.metadata:
            # LangGraph stores pending writes info in checkpoint metadata
            pass
        # Alternative: read from the WorkflowRun or the checkpoint's pending_sends
        # For now, query via the graph state if pipeline_name is available
        if run.pipeline:
            try:
                from src.db import get_checkpointer
                from src.engine.graph import build_graph

                pipeline = load_pipeline(
                    str(resolve_pipeline_file(run.pipeline, run.project_id))
                )
                checkpointer = await get_checkpointer()
                abort_signal = asyncio.Event()
                run_id_int = await _resolve_run_id_int(run_id)

                compiled = build_graph(
                    pipeline,
                    run_id=run_id,
                    run_id_int=run_id_int,
                    abort_signal=abort_signal,
                    permission_mode="normal",
                    checkpointer=checkpointer,
                )
                graph_state = await compiled.aget_state(config)
                if graph_state.next:
                    paused_node = graph_state.next[0]
                    result["paused_at"] = paused_node.replace("_interrupt", "")
            except Exception:
                logger.warning("Could not determine paused_at node", exc_info=True)

    return result


# ── Node execution ────────────────────────────────────────


async def _run_node(
    node: NodeDefinition,
    task_description: str,
    project_id: int,
    run_id: str,
    run_id_int: int,
    abort_signal: asyncio.Event,
    permission_mode: object | None = None,
    mcp_manager: object | None = None,
) -> str:
    """Execute a single node: create agent, run loop, return output text."""
    from src.agent.factory import create_agent
    from src.agent.loop import run_agent_to_completion
    from src.agent.runs import complete_agent_run, create_agent_run, fail_agent_run
    from src.agent.state import ExitReason
    from src.tools.builtins.spawn_agent import extract_final_output

    # Create AgentRun audit record
    agent_id = f"{run_id}:{node.role}"
    agent_run = await create_agent_run(
        run_id=run_id_int,
        role=node.role,
        description=task_description[:500],
        owner=agent_id,
    )

    try:
        state = await create_agent(
            role=node.role,
            task_description=task_description,
            project_id=project_id,
            run_id=run_id,
            abort_signal=abort_signal,
            permission_mode=permission_mode,
            mcp_manager=mcp_manager,
        )
        exit_reason = await run_agent_to_completion(state)
        output = extract_final_output(state.messages)

        if exit_reason == ExitReason.COMPLETED:
            await complete_agent_run(agent_run.id, output or "(no output)")
        elif exit_reason == ExitReason.MAX_TURNS:
            await complete_agent_run(agent_run.id, f"[MAX_TURNS] {output}")
        else:
            await fail_agent_run(agent_run.id, f"[{exit_reason.value}] {output}")
            raise RuntimeError(f"Node '{node.name}' exited with {exit_reason.value}")

        return output or "(no output)"

    except Exception:
        await fail_agent_run(agent_run.id, f"[ERROR] {__import__('traceback').format_exc()}")
        raise


# ── Helpers ───────────────────────────────────────────────


def _build_task_description(
    node: NodeDefinition,
    node_outputs: dict[str, str],
    user_input: str,
) -> str:
    """Build the task_description for a node."""
    if not node.input:
        return user_input

    sections: list[str] = []
    for input_name in node.input:
        content = node_outputs.get(input_name, "")
        sections.append(f"## {input_name}\n{content}")

    return f"{user_input}\n\n--- 输入数据 ---\n\n" + "\n\n".join(sections) + "\n\n--- 输入数据结束 ---"


def _find_terminal_outputs(pipeline: PipelineDefinition) -> list[str]:
    """Find output names of terminal nodes (nodes that no other node depends on)."""
    all_inputs: set[str] = set()
    for node in pipeline.nodes:
        all_inputs.update(node.input)

    return [
        node.output
        for node in pipeline.nodes
        if node.output not in all_inputs
    ]


async def _resolve_run_id_int(run_id: str) -> int:
    """Convert run_id string to workflow_runs.id integer."""
    from sqlalchemy import select

    from src.db import get_db
    from src.models import WorkflowRun

    async with get_db() as session:
        result = await session.execute(
            select(WorkflowRun.id).where(WorkflowRun.run_id == run_id)
        )
        row = result.scalar()
        if row is None:
            raise ValueError(f"WorkflowRun with run_id='{run_id}' not found")
        return row
