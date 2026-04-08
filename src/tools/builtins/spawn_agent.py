"""Built-in tool: spawn_agent — asynchronously launch a sub-agent."""

from __future__ import annotations

import asyncio
import logging

from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


def extract_final_output(messages: list[dict]) -> str:
    """Extract the last assistant message with text content.

    Searches backwards through messages for the most recent assistant message
    that has a non-empty content string. Mirrors CC's finalizeAgentTool() logic.
    """
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if content and isinstance(content, str) and content.strip():
                return content.strip()
    return ""


class SpawnAgentTool(Tool):
    name = "spawn_agent"
    description = (
        "Launch a sub-agent to handle a task asynchronously. "
        "Returns a task_id immediately. Use task_list / task_get to check status and retrieve results."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "description": "Role file name without .md extension (e.g. 'researcher', 'writer').",
            },
            "task_description": {
                "type": "string",
                "description": "The task for the sub-agent to perform. Injected as a user message.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: override the role file's tool whitelist.",
            },
        },
        "required": ["role", "task_description"],
    }

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.task.manager import claim_task, create_task

        role: str = params["role"]
        task_description: str = params["task_description"]
        tools_override: list[str] | None = params.get("tools")

        # Resolve run_id to int for task creation
        run_id_int = await self._resolve_run_id(context)

        # Create a Task record to track the sub-agent
        task = await create_task(
            run_id=run_id_int,
            subject=f"{role}: {task_description[:100]}",
            description=task_description,
        )
        task_id = task.id

        # Claim the task
        agent_id = f"{context.run_id}:{role}" if context.run_id else role
        await claim_task(task_id, agent_id)

        # Launch background coroutine
        asyncio.create_task(
            self._run_agent_background(
                task_id=task_id,
                role=role,
                task_description=task_description,
                context=context,
                tools_override=tools_override,
            )
        )

        return ToolResult(
            output=f"Sub-agent '{role}' launched (task_id={task_id}). Use task_list or task_get to check status.",
            metadata={"task_id": task_id, "role": role},
        )

    async def _run_agent_background(
        self,
        task_id: int,
        role: str,
        task_description: str,
        context: ToolContext,
        tools_override: list[str] | None,
    ) -> None:
        """Background coroutine: run agent loop, then update task."""
        from src.agent.factory import create_agent
        from src.agent.loop import agent_loop
        from src.agent.state import ExitReason
        from src.task.manager import complete_task, fail_task

        try:
            state = await create_agent(
                role=role,
                task_description=task_description,
                project_id=context.project_id,
                run_id=context.run_id,
                tools_override=tools_override,
                abort_signal=context.abort_signal,
            )

            exit_reason = await agent_loop(state)
            output = extract_final_output(state.messages)

            if exit_reason == ExitReason.COMPLETED:
                await complete_task(task_id, output or "(no output)")
            elif exit_reason == ExitReason.MAX_TURNS:
                await complete_task(task_id, f"[MAX_TURNS] {output}")
            elif exit_reason == ExitReason.ABORT:
                await fail_task(task_id, f"[ABORT] agent aborted. {output}")
            else:
                await fail_task(task_id, f"[ERROR] agent failed. {output}")

        except Exception as exc:
            logger.exception("Sub-agent '%s' (task %d) raised exception", role, task_id)
            await fail_task(task_id, f"[ERROR] {exc}")

    async def _resolve_run_id(self, context: ToolContext) -> int:
        """Convert context.run_id (str) to workflow_runs.id (int).

        If context has no run_id, create a new workflow run.
        """
        from sqlalchemy import select

        from src.db import get_db
        from src.engine.run import create_run
        from src.models import WorkflowRun

        if context.run_id:
            async with get_db() as session:
                result = await session.execute(
                    select(WorkflowRun.id).where(WorkflowRun.run_id == context.run_id)
                )
                row = result.scalar()
                if row is not None:
                    return row

        # Fallback: create a new run
        run = await create_run(project_id=context.project_id or 0)
        return run.id
