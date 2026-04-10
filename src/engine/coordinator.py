"""Coordinator: autonomous agent mode with sub-agent spawning."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator  # noqa: TC003
from dataclasses import dataclass

from src.agent.state import AgentState, ExitReason  # noqa: TC001 — used at runtime
from src.streaming.events import StreamEvent  # noqa: TC001 — used at runtime

logger = logging.getLogger(__name__)


@dataclass
class CoordinatorResult:
    """Return from autonomous coordinator mode."""

    run_id: str
    output: str
    agent_runs: list[dict] | None = None


# ── coordinator_loop ─────────────────────────────────────


async def coordinator_loop(state: AgentState) -> AsyncIterator[StreamEvent]:
    """Outer do-while loop wrapping agent_loop for coordinator mode.

    Yields all StreamEvent from inner agent_loop iterations.
    Waits for sub-agent notifications via asyncio.Queue, then re-enters
    agent_loop with injected notification messages. Zero LLM cost during wait.
    Sets state.exit_reason before ending.
    """
    from src.agent.loop import agent_loop

    # Initialize notification infrastructure on state
    state.notification_queue = asyncio.Queue()
    state.running_agent_count = 0

    while True:
        # Yield all events from agent_loop
        async for event in agent_loop(state):
            yield event

        # No background agents → truly done
        if state.running_agent_count == 0:
            # state.exit_reason already set by agent_loop
            return

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


async def run_coordinator_to_completion(state: AgentState) -> ExitReason:
    """Consume all events from coordinator_loop, return exit reason."""
    async for _event in coordinator_loop(state):
        pass
    return state.exit_reason  # type: ignore[return-value]


# ── run_coordinator ──────────────────────────────────────


async def run_coordinator(
    project_id: int,
    user_input: str,
) -> CoordinatorResult:
    """Autonomous coordinator mode: spawn sub-agents via coordinator_loop.

    Pipeline routing is handled by the caller — this function only does
    autonomous mode (coordinator agent + spawn_agent notifications).

    1. Creates a WorkflowRun
    2. Creates coordinator agent, runs coordinator_loop
    3. Returns CoordinatorResult with agent audit records
    """
    from src.agent.factory import create_agent
    from src.agent.runs import list_agent_runs
    from src.engine.run import RunStatus, create_run, finish_run, update_run_status
    from src.permissions.types import PermissionMode
    from src.tools.builtins.spawn_agent import extract_final_output

    # Create WorkflowRun
    workflow_run = await create_run(project_id=project_id)
    run_id = workflow_run.run_id

    try:
        await update_run_status(run_id, RunStatus.RUNNING)

        state = await create_agent(
            role="coordinator",
            task_description=user_input,
            project_id=project_id,
            run_id=run_id,
            abort_signal=asyncio.Event(),
            permission_mode=PermissionMode.NORMAL,
        )

        # Set parent_state so spawn_agent can push notifications
        state.tool_context.parent_state = state

        await run_coordinator_to_completion(state)
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
