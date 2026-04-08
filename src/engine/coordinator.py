"""Coordinator: unified entry point for pipeline and autonomous modes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from src.agent.state import AgentState, ExitReason

logger = logging.getLogger(__name__)

_PIPELINES_DIR = Path(__file__).resolve().parent.parent.parent / "pipelines"


@dataclass
class CoordinatorResult:
    """Unified return from both pipeline and autonomous modes."""

    run_id: str
    mode: str  # 'pipeline' / 'autonomous'
    output: str
    node_outputs: dict[str, str] | None = None
    agent_runs: list[dict] | None = None


# ── coordinator_loop ─────────────────────────────────────


async def coordinator_loop(state: AgentState) -> ExitReason:
    """Outer do-while loop wrapping agent_loop for coordinator mode.

    Waits for sub-agent notifications via asyncio.Queue, then re-enters
    agent_loop with injected notification messages. Zero LLM cost during wait.
    """
    from src.agent.loop import agent_loop

    # Initialize notification infrastructure on state
    state.notification_queue = asyncio.Queue()
    state.running_agent_count = 0

    while True:
        exit_reason = await agent_loop(state)

        # No background agents → truly done
        if state.running_agent_count == 0:
            return exit_reason

        # Wait for at least one notification (blocks, zero LLM cost)
        notification = await state.notification_queue.get()
        notifications = [notification]

        # Drain all immediately available notifications
        while not state.notification_queue.empty():
            notifications.append(state.notification_queue.get_nowait())

        # Inject notifications as user messages
        for n in notifications:
            state.messages.append({"role": "user", "content": n["message"]})

        # Re-enter agent_loop to process new messages


# ── run_coordinator ──────────────────────────────────────


async def run_coordinator(
    project_id: int,
    user_input: str,
) -> CoordinatorResult:
    """Unified entry point: route to pipeline mode or autonomous mode.

    1. Creates a WorkflowRun
    2. Checks Project.pipeline field
    3. Pipeline mode → execute_pipeline
    4. Autonomous mode → coordinator_loop with Coordinator Agent
    """
    from sqlalchemy import select

    from src.agent.factory import create_agent
    from src.agent.runs import list_agent_runs
    from src.db import get_db
    from src.engine.pipeline import execute_pipeline
    from src.engine.run import RunStatus, create_run, finish_run, update_run_status
    from src.models import Project
    from src.tools.builtins.spawn_agent import extract_final_output

    # 1. Look up project
    async with get_db() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalars().first()
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    pipeline_name = project.pipeline if project.pipeline else None

    # 2. Create WorkflowRun
    workflow_run = await create_run(
        project_id=project_id,
        pipeline=pipeline_name,
    )
    run_id = workflow_run.run_id

    try:
        # 3. Route
        if pipeline_name:
            # Pipeline mode: verify YAML exists
            yaml_path = _PIPELINES_DIR / f"{pipeline_name}.yaml"
            if not yaml_path.is_file():
                raise FileNotFoundError(
                    f"Pipeline YAML not found: {yaml_path}"
                )

            await update_run_status(run_id, RunStatus.RUNNING)
            pipeline_result = await execute_pipeline(
                pipeline_name, run_id, project_id, user_input
            )

            return CoordinatorResult(
                run_id=run_id,
                mode="pipeline",
                output=pipeline_result.final_output,
                node_outputs=pipeline_result.outputs,
            )

        else:
            # Autonomous mode
            await update_run_status(run_id, RunStatus.RUNNING)

            state = await create_agent(
                role="coordinator",
                task_description=user_input,
                project_id=project_id,
                run_id=run_id,
                abort_signal=asyncio.Event(),
            )

            # Set parent_state so spawn_agent can push notifications
            state.tool_context.parent_state = state

            exit_reason = await coordinator_loop(state)
            output = extract_final_output(state.messages)

            # Fetch audit records
            run_id_int = workflow_run.id
            runs = await list_agent_runs(run_id_int)
            agent_run_dicts = [
                {
                    "id": r.id,
                    "role": r.role,
                    "status": r.status,
                    "result": r.result,
                }
                for r in runs
            ]

            await finish_run(run_id, RunStatus.COMPLETED)

            return CoordinatorResult(
                run_id=run_id,
                mode="autonomous",
                output=output,
                agent_runs=agent_run_dicts,
            )

    except Exception:
        logger.exception("Coordinator failed for project %d", project_id)
        try:
            await finish_run(run_id, RunStatus.FAILED)
        except Exception:
            logger.warning("Failed to mark run %s as FAILED", run_id)
        raise
