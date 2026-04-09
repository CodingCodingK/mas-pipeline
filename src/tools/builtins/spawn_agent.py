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


def format_task_notification(
    agent_run_id: int, role: str, status: str, result: str
) -> str:
    """Format a CC-style <task-notification> XML string."""
    return (
        f"<task-notification>\n"
        f"<agent-run-id>{agent_run_id}</agent-run-id>\n"
        f"<role>{role}</role>\n"
        f"<status>{status}</status>\n"
        f"<result>{result}</result>\n"
        f"</task-notification>"
    )


class SpawnAgentTool(Tool):
    name = "spawn_agent"
    description = (
        "Launch a sub-agent to handle a task asynchronously. "
        "Returns immediately. Results arrive as notifications."
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
        from src.agent.runs import create_agent_run

        role: str = params["role"]
        task_description: str = params["task_description"]
        tools_override: list[str] | None = params.get("tools")

        # Resolve run_id to int for record creation
        run_id_int = await self._resolve_run_id(context)

        # Create an AgentRun audit record (directly as running)
        agent_id = f"{context.run_id}:{role}" if context.run_id else role
        agent_run = await create_agent_run(
            run_id=run_id_int,
            role=role,
            description=task_description[:500],
            owner=agent_id,
        )
        agent_run_id = agent_run.id

        # Increment running counter on parent state (for coordinator_loop)
        if context.parent_state and context.parent_state.notification_queue is not None:
            context.parent_state.running_agent_count += 1

        # Fire SubagentStart hook
        await self._fire_hook(context, "subagent_start", {
            "agent_run_id": agent_run_id,
            "role": role,
            "task_description": task_description,
            "parent_run_id": context.run_id,
        })

        # Launch background coroutine
        asyncio.create_task(
            self._run_agent_background(
                agent_run_id=agent_run_id,
                role=role,
                task_description=task_description,
                context=context,
                tools_override=tools_override,
            )
        )

        return ToolResult(
            output=f"Sub-agent '{role}' launched (agent_run_id={agent_run_id}). Results will arrive as notifications.",
            metadata={"agent_run_id": agent_run_id, "role": role},
        )

    async def _run_agent_background(
        self,
        agent_run_id: int,
        role: str,
        task_description: str,
        context: ToolContext,
        tools_override: list[str] | None,
    ) -> None:
        """Background coroutine: run agent loop, then write record + push notification."""
        from src.agent.factory import create_agent
        from src.agent.loop import run_agent_to_completion
        from src.agent.runs import complete_agent_run, fail_agent_run
        from src.agent.state import ExitReason

        status = "failed"
        result = ""

        try:
            # Inherit parent deny rules + permission mode
            parent_deny_rules = None
            permission_mode = None
            if context.permission_checker is not None:
                parent_deny_rules = context.permission_checker.get_deny_rules()
                permission_mode = context.permission_checker._mode

            # Lazy import to get default
            if permission_mode is None:
                from src.permissions.types import PermissionMode
                permission_mode = PermissionMode.NORMAL

            state = await create_agent(
                role=role,
                task_description=task_description,
                project_id=context.project_id,
                run_id=context.run_id,
                tools_override=tools_override,
                abort_signal=context.abort_signal,
                permission_mode=permission_mode,
                parent_deny_rules=parent_deny_rules,
            )

            exit_reason = await run_agent_to_completion(state)
            output = extract_final_output(state.messages)

            if exit_reason == ExitReason.COMPLETED:
                await complete_agent_run(agent_run_id, output or "(no output)")
                status = "completed"
                result = output or "(no output)"
            elif exit_reason == ExitReason.MAX_TURNS:
                await complete_agent_run(agent_run_id, f"[MAX_TURNS] {output}")
                status = "completed"
                result = f"[MAX_TURNS] {output}"
            elif exit_reason == ExitReason.ABORT:
                await fail_agent_run(agent_run_id, f"[ABORT] agent aborted. {output}")
                status = "failed"
                result = f"[ABORT] agent aborted. {output}"
            else:
                await fail_agent_run(agent_run_id, f"[ERROR] agent failed. {output}")
                status = "failed"
                result = f"[ERROR] agent failed. {output}"

        except Exception as exc:
            logger.exception("Sub-agent '%s' (agent_run %d) raised exception", role, agent_run_id)
            await fail_agent_run(agent_run_id, f"[ERROR] {exc}")
            status = "failed"
            result = f"[ERROR] {exc}"

        # Push notification to parent's queue (CC-style enqueueAgentNotification)
        if context.parent_state and context.parent_state.notification_queue is not None:
            notification = {
                "agent_run_id": agent_run_id,
                "role": role,
                "status": status,
                "result": result,
                "message": format_task_notification(agent_run_id, role, status, result),
            }
            await context.parent_state.notification_queue.put(notification)
            context.parent_state.running_agent_count -= 1

        # Fire SubagentEnd hook
        await self._fire_hook(context, "subagent_end", {
            "agent_run_id": agent_run_id,
            "role": role,
            "status": status,
            "result": result,
            "parent_run_id": context.run_id,
        })

    @staticmethod
    async def _fire_hook(context: ToolContext, event_name: str, payload: dict) -> None:
        """Fire a lifecycle hook if hook_runner is available."""
        if not context.hook_runner:
            return
        try:
            from src.hooks.types import HookEvent, HookEventType
            event = HookEvent(
                event_type=HookEventType(event_name),
                payload=payload,
            )
            await context.hook_runner.run(event)
        except Exception:
            logger.warning("Hook %s failed (non-blocking)", event_name, exc_info=True)

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
