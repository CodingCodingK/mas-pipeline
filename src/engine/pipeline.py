"""Pipeline engine: YAML definition loading, dependency inference, and reactive execution."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Pipelines directory relative to project root
_PIPELINES_DIR = Path(__file__).resolve().parent.parent.parent / "pipelines"


# ── Data structures ───────────────────────────────────────


@dataclass
class NodeDefinition:
    name: str
    role: str
    output: str
    input: list[str] = field(default_factory=list)


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
    status: str                             # 'completed' / 'failed'
    outputs: dict[str, str]                 # output_name → content
    final_output: str
    failed_node: str | None = None
    error: str | None = None


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
    """Execute a pipeline: load YAML, run nodes with reactive scheduling.

    The caller must have already created a WorkflowRun with this run_id.
    Creates an MCPManager from settings, starts MCP servers before node
    execution, and shuts them down when the pipeline completes.
    """
    from src.engine.run import RunStatus, finish_run, update_run_status
    from src.mcp.manager import MCPManager
    from src.permissions.types import PermissionMode
    from src.project.config import get_settings

    if permission_mode is None:
        permission_mode = PermissionMode.NORMAL

    # Load pipeline
    yaml_path = str(_PIPELINES_DIR / f"{pipeline_name}.yaml")
    pipeline = load_pipeline(yaml_path)

    # Start MCP servers
    mcp_manager = MCPManager()
    settings = get_settings()
    if settings.mcp_servers:
        await mcp_manager.start(settings.mcp_servers)

    try:
        # Fire PipelineStart hook
        await _fire_pipeline_hook(hook_runner, "pipeline_start", {
            "pipeline_name": pipeline_name,
            "run_id": run_id,
            "project_id": project_id,
            "user_input": user_input,
        })

        # Transition run: pending → running
        await update_run_status(run_id, RunStatus.RUNNING)

        # Resolve run_id str → workflow_runs.id for task creation
        run_id_int = await _resolve_run_id_int(run_id)

        # Shared abort signal
        abort_signal = asyncio.Event()

        # Node lookup by name
        node_by_name: dict[str, NodeDefinition] = {n.name: n for n in pipeline.nodes}

        # State
        node_outputs: dict[str, str] = {}       # output_name → content
        pending: set[str] = {n.name for n in pipeline.nodes}
        running: dict[str, asyncio.Task] = {}   # node_name → asyncio.Task
        skipped: set[str] = set()
        failed_node: str | None = None
        failed_error: str | None = None

        try:
            while pending or running:
                # Find ready nodes
                ready: list[str] = []
                for name in list(pending):
                    if name in skipped:
                        pending.discard(name)
                        continue
                    node = node_by_name[name]
                    if all(inp in node_outputs for inp in node.input):
                        ready.append(name)

                # Start ready nodes
                for name in ready:
                    pending.discard(name)
                    node = node_by_name[name]
                    task_desc = _build_task_description(node, node_outputs, user_input)
                    coro = _run_node(
                        node=node,
                        task_description=task_desc,
                        project_id=project_id,
                        run_id=run_id,
                        run_id_int=run_id_int,
                        abort_signal=abort_signal,
                        permission_mode=permission_mode,
                        mcp_manager=mcp_manager,
                    )
                    running[name] = asyncio.create_task(coro)
                    logger.info("Node '%s' started", name)

                if not running:
                    # No running tasks and nothing ready — all remaining are skipped
                    break

                # Wait for any node to complete
                done, _ = await asyncio.wait(
                    running.values(), return_when=asyncio.FIRST_COMPLETED
                )

                # Harvest completed nodes
                for async_task in done:
                    name = _find_name(async_task, running)
                    del running[name]

                    exc = async_task.exception()
                    if exc is not None:
                        logger.error("Node '%s' failed: %s", name, exc)
                        failed_node = name
                        failed_error = str(exc)
                        # Mark all downstream nodes as skipped
                        _mark_downstream_skipped(
                            name, pipeline.dependencies, node_by_name, pending, skipped
                        )
                    else:
                        output_content = async_task.result()
                        node = node_by_name[name]
                        node_outputs[node.output] = output_content
                        logger.info("Node '%s' completed", name)

        except Exception as exc:
            logger.exception("Pipeline execution failed")
            failed_error = str(exc)

        # Determine final status
        if failed_node:
            status = "failed"
            await finish_run(run_id, RunStatus.FAILED)
        else:
            status = "completed"
            await finish_run(run_id, RunStatus.COMPLETED)

        # Find terminal node output (last node with no downstream dependents)
        terminal_outputs = _find_terminal_outputs(pipeline)
        final_output = ""
        for out_name in terminal_outputs:
            if out_name in node_outputs:
                final_output = node_outputs[out_name]
                break

        # Fire PipelineEnd hook
        await _fire_pipeline_hook(hook_runner, "pipeline_end", {
            "pipeline_name": pipeline_name,
            "run_id": run_id,
            "status": status,
            "error": failed_error,
        })

        return PipelineResult(
            run_id=run_id,
            status=status,
            outputs=node_outputs,
            final_output=final_output,
            failed_node=failed_node,
            error=failed_error,
        )

    finally:
        await mcp_manager.shutdown()


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


def _find_name(task: asyncio.Task, running: dict[str, asyncio.Task]) -> str:
    """Find the node name for a completed asyncio.Task."""
    for name, t in running.items():
        if t is task:
            return name
    raise RuntimeError("Completed task not found in running dict")


def _mark_downstream_skipped(
    failed_name: str,
    dependencies: dict[str, set[str]],
    node_by_name: dict[str, NodeDefinition],
    pending: set[str],
    skipped: set[str],
) -> None:
    """Mark all transitive downstream nodes of a failed node as skipped."""
    # Build reverse dependency map: node → set of nodes that depend on it
    reverse: dict[str, set[str]] = defaultdict(set)
    for name, deps in dependencies.items():
        for dep in deps:
            reverse[dep].add(name)

    # BFS from failed node
    queue = [failed_name]
    while queue:
        current = queue.pop(0)
        for downstream in reverse.get(current, set()):
            if downstream not in skipped:
                skipped.add(downstream)
                pending.discard(downstream)
                logger.info("Node '%s' skipped (upstream '%s' failed)", downstream, failed_name)
                queue.append(downstream)


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
