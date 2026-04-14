"""Built-in tool: spawn_agent — asynchronously launch a sub-agent.

Phase 6.1: notifications are persisted as messages on the parent's
Conversation (PG) and the parent SessionRunner is woken via its
in-process asyncio.Event. A best-effort PG NOTIFY signals other
processes (forward-compat for multi-worker deployments).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from src.agent.loop import extract_final_output
from src.telemetry import current_spawn_id, get_collector
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# Roles that must never be launched as a sub-agent. ClawBot is a top-level
# chat agent with bus-attached identity (channel/chat_id on its tool_context)
# and must not be reinstantiated inside a pipeline run where that identity
# would be missing.
SUB_AGENT_DISALLOWED_ROLES: frozenset[str] = frozenset({"clawbot"})


def _snapshot_partial(state: object) -> dict:
    """Best-effort snapshot of a crashed sub-agent's partial transcript + stats.

    Used by timeout / cancel / unhandled-exception branches so fail_agent_run
    can still persist whatever the loop had accumulated before dying. Returns
    the keyword arguments for complete_agent_run / fail_agent_run.
    """
    messages = getattr(state, "messages", None) or []
    return {
        "messages": list(messages) if isinstance(messages, list) else [],
        "tool_use_count": int(getattr(state, "tool_use_count", 0) or 0),
        "total_tokens": int(getattr(state, "cumulative_tokens", 0) or 0),
        "duration_ms": 0,  # monotonic unknown at crash site — honest zero
    }


def format_task_notification(
    agent_run_id: int,
    role: str,
    status: str,
    result: str,
    tool_use_count: int,
    total_tokens: int,
    duration_ms: int,
) -> str:
    """Format a CC-style <task-notification> XML string.

    Field order is canonical: id, role, status, statistics, result.
    Statistics are placed between status and result so main agent models
    skimming the prefix can cost-gate before paying to parse the body.
    """
    return (
        f"<task-notification>\n"
        f"<agent-run-id>{agent_run_id}</agent-run-id>\n"
        f"<role>{role}</role>\n"
        f"<status>{status}</status>\n"
        f"<tool-use-count>{tool_use_count}</tool-use-count>\n"
        f"<total-tokens>{total_tokens}</total-tokens>\n"
        f"<duration-ms>{duration_ms}</duration-ms>\n"
        f"<result>{result}</result>\n"
        f"</task-notification>"
    )


def _build_notification_message(
    agent_run_id: int,
    role: str,
    status: str,
    result: str,
    tool_use_count: int,
    total_tokens: int,
    duration_ms: int,
) -> dict:
    """Wrap a task notification as a user-role message dict for Conversation.messages."""
    return {
        "role": "user",
        "content": format_task_notification(
            agent_run_id, role, status, result,
            tool_use_count, total_tokens, duration_ms,
        ),
        "metadata": {
            "kind": "task_notification",
            "agent_run_id": agent_run_id,
            "sub_agent_role": role,
            "status": status,
            "tool_use_count": tool_use_count,
            "total_tokens": total_tokens,
            "duration_ms": duration_ms,
        },
    }


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

        if role in SUB_AGENT_DISALLOWED_ROLES:
            return ToolResult(
                output=f"Error: role '{role}' cannot be launched as a sub-agent.",
                success=False,
            )

        run_id_int = await self._resolve_run_id(context)

        agent_id = f"{context.run_id}:{role}" if context.run_id else role
        agent_run = await create_agent_run(
            run_id=run_id_int,
            role=role,
            description=task_description[:500],
            owner=agent_id,
        )
        agent_run_id = agent_run.id

        await self._fire_hook(context, "subagent_start", {
            "agent_run_id": agent_run_id,
            "role": role,
            "task_description": task_description,
            "parent_run_id": context.run_id,
        })

        # Telemetry: emit agent_spawn; derive parent_role from parent runner if
        # present, else fall back to "unknown". Set current_spawn_id so the
        # child task inherits it and its first agent_turn records
        # spawned_by_spawn_id.
        spawn_id = uuid.uuid4().hex
        parent_runner = self._lookup_parent_runner(context)
        parent_role = "unknown"
        if parent_runner is not None:
            from src.engine.session_runner import _MODE_TO_ROLE
            parent_role = _MODE_TO_ROLE.get(parent_runner.mode, "unknown")
        get_collector().record_agent_spawn(
            parent_role=parent_role,
            child_role=role,
            task_preview=task_description,
            spawn_id=spawn_id,
        )
        prev_spawn_id = current_spawn_id.set(spawn_id)

        # Launch background coroutine. Track it on the parent SessionRunner so
        # graceful shutdown can cancel it.  The child task inherits the
        # current_spawn_id via ContextVar copy-on-create_task; reset the
        # parent's value immediately so it doesn't leak into subsequent turns.
        task = asyncio.create_task(
            self._run_agent_background(
                agent_run_id=agent_run_id,
                role=role,
                task_description=task_description,
                context=context,
                tools_override=tools_override,
            ),
            name=f"spawn_agent:{role}:{agent_run_id}",
        )
        current_spawn_id.reset(prev_spawn_id)

        if parent_runner is not None:
            parent_runner.child_tasks.add(task)
            task.add_done_callback(parent_runner.child_tasks.discard)
            parent_runner.state.running_agent_count += 1  # type: ignore[union-attr]

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
        """Background coroutine: run agent loop, then persist notification + wake parent.

        Hard contract: NEVER propagate exceptions. Any failure persists a
        failure notification and is logged at ERROR.
        """
        from src.agent.factory import create_agent
        from src.agent.loop import run_agent_to_completion
        from src.agent.runs import complete_agent_run, fail_agent_run
        from src.agent.state import ExitReason
        from src.project.config import get_settings

        status = "failed"
        result = ""
        stats = {"tool_use_count": 0, "total_tokens": 0, "duration_ms": 0}
        state: object = None  # populated after create_agent for best-effort failure persist
        timeout_seconds = get_settings().spawn_agent.timeout_seconds

        try:
            try:
                # Inherit parent deny rules + permission mode
                parent_deny_rules = None
                permission_mode = None
                if context.permission_checker is not None:
                    parent_deny_rules = context.permission_checker.get_deny_rules()
                    permission_mode = context.permission_checker._mode

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
                    is_spawned=True,
                    permission_mode=permission_mode,
                    parent_deny_rules=parent_deny_rules,
                )

                # Forward parent SessionRunner addressing so nested spawns route
                # back to the same conversation.
                state.tool_context.session_id = context.session_id
                state.tool_context.conversation_id = context.conversation_id

                from src.telemetry import get_collector

                collector = get_collector()
                async with collector.turn_context(
                    agent_role=role,
                    input_preview=task_description[:200],
                    session_id=context.session_id,
                    project_id=context.project_id,
                ) as turn_capture:
                    run_result = await asyncio.wait_for(
                        run_agent_to_completion(state),
                        timeout=timeout_seconds,
                    )
                    turn_capture["output"] = (run_result.final_output or "")[:200]
                    turn_capture["stop_reason"] = (
                        run_result.exit_reason.value if run_result.exit_reason else "done"
                    )

                exit_reason = run_result.exit_reason
                output = run_result.final_output
                stats = {
                    "tool_use_count": run_result.tool_use_count,
                    "total_tokens": run_result.cumulative_tokens,
                    "duration_ms": run_result.duration_ms,
                }
                run_messages = run_result.messages

                if exit_reason == ExitReason.COMPLETED:
                    await complete_agent_run(
                        agent_run_id, output or "(no output)",
                        run_messages, **stats,
                    )
                    status = "completed"
                    result = output or "(no output)"
                elif exit_reason == ExitReason.MAX_TURNS:
                    await complete_agent_run(
                        agent_run_id, f"[MAX_TURNS] {output}",
                        run_messages, **stats,
                    )
                    status = "completed"
                    result = f"[MAX_TURNS] {output}"
                elif exit_reason == ExitReason.ABORT:
                    await fail_agent_run(
                        agent_run_id, f"[ABORT] agent aborted. {output}",
                        run_messages, **stats,
                    )
                    status = "failed"
                    result = f"[ABORT] agent aborted. {output}"
                else:
                    await fail_agent_run(
                        agent_run_id, f"[ERROR] agent failed. {output}",
                        run_messages, **stats,
                    )
                    status = "failed"
                    result = f"[ERROR] agent failed. {output}"

            except asyncio.TimeoutError:
                logger.error(
                    "Sub-agent '%s' (agent_run %d) exceeded %ds timeout",
                    role, agent_run_id, timeout_seconds,
                )
                partial = _snapshot_partial(state)
                await fail_agent_run(
                    agent_run_id,
                    f"[TIMEOUT] sub-agent exceeded {timeout_seconds}s",
                    **partial,
                )
                stats = {k: partial[k] for k in ("tool_use_count", "total_tokens", "duration_ms")}
                status = "failed"
                result = f"[TIMEOUT] sub-agent exceeded {timeout_seconds}s"
            except asyncio.CancelledError:
                logger.warning("Sub-agent '%s' (agent_run %d) cancelled", role, agent_run_id)
                partial = _snapshot_partial(state)
                try:
                    await fail_agent_run(
                        agent_run_id, "[CANCELLED] sub-agent cancelled", **partial,
                    )
                except Exception:
                    logger.exception("Failed to mark cancelled agent_run %d", agent_run_id)
                stats = {k: partial[k] for k in ("tool_use_count", "total_tokens", "duration_ms")}
                status = "failed"
                result = "[CANCELLED] sub-agent cancelled"
                # Do not re-raise — we still want to persist the notification.
            except Exception as exc:
                logger.exception(
                    "Sub-agent '%s' (agent_run %d) raised exception", role, agent_run_id
                )
                partial = _snapshot_partial(state)
                try:
                    await fail_agent_run(
                        agent_run_id, f"[ERROR] {exc}", **partial,
                    )
                except Exception:
                    logger.exception("Failed to mark failed agent_run %d", agent_run_id)
                stats = {k: partial[k] for k in ("tool_use_count", "total_tokens", "duration_ms")}
                status = "failed"
                result = f"[ERROR] {exc}"

            # Persist notification + wake parent. Best-effort: any failure here
            # is logged but never propagated.
            await self._notify_parent(
                agent_run_id=agent_run_id,
                role=role,
                status=status,
                result=result,
                tool_use_count=stats["tool_use_count"],
                total_tokens=stats["total_tokens"],
                duration_ms=stats["duration_ms"],
                context=context,
            )

            await self._fire_hook(context, "subagent_end", {
                "agent_run_id": agent_run_id,
                "role": role,
                "status": status,
                "result": result,
                "parent_run_id": context.run_id,
            })

        except Exception:
            # Catch-all: this coroutine MUST NOT propagate.
            logger.exception(
                "spawn_agent background task crashed (agent_run %d)", agent_run_id
            )
        finally:
            parent_runner = self._lookup_parent_runner(context)
            if parent_runner is not None and parent_runner.state is not None:
                parent_runner.state.running_agent_count = max(
                    0, parent_runner.state.running_agent_count - 1
                )

    async def _notify_parent(
        self,
        agent_run_id: int,
        role: str,
        status: str,
        result: str,
        tool_use_count: int,
        total_tokens: int,
        duration_ms: int,
        context: ToolContext,
    ) -> None:
        """Persist task notification + wake parent runner (in-proc + cross-proc)."""
        from src.session.manager import append_message

        message = _build_notification_message(
            agent_run_id, role, status, result,
            tool_use_count, total_tokens, duration_ms,
        )

        if context.conversation_id is not None:
            try:
                await append_message(context.conversation_id, message)
            except Exception:
                logger.exception(
                    "Failed to persist task notification for agent_run %d", agent_run_id
                )
        else:
            logger.warning(
                "spawn_agent: no conversation_id on tool_context, skipping persist (agent_run %d)",
                agent_run_id,
            )

        # In-process wakeup
        parent_runner = self._lookup_parent_runner(context)
        if parent_runner is not None:
            parent_runner.notify_new_message()

        # Cross-process wakeup (best-effort)
        if context.session_id is not None:
            await self._notify_session_wakeup(context.session_id)

    @staticmethod
    def _lookup_parent_runner(context: ToolContext):
        """Look up the parent SessionRunner if it lives in this process."""
        if context.session_id is None:
            return None
        try:
            from src.engine.session_registry import get_runner
            return get_runner(context.session_id)
        except Exception:
            logger.exception("Failed to look up parent SessionRunner")
            return None

    @staticmethod
    async def _notify_session_wakeup(session_id: int) -> None:
        """Best-effort PG NOTIFY session_wakeup '<session_id>'.

        Failure here is non-fatal — the in-process wakeup already covers the
        local case, and a future GC sweep will catch any missed cross-process
        notification.
        """
        try:
            from sqlalchemy import text

            from src.db import get_db

            async with get_db() as session:
                # Use parameter binding via SET LOCAL to avoid SQL injection
                # since NOTIFY does not accept parameters.
                payload = str(int(session_id))
                await session.execute(text(f"NOTIFY session_wakeup, '{payload}'"))
                await session.commit()
        except Exception:
            logger.debug("PG NOTIFY session_wakeup failed (non-fatal)", exc_info=True)

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

    _run_id_cache: dict[str, int] = {}

    async def _resolve_run_id(self, context: ToolContext) -> int:
        """Convert context.run_id (str) to workflow_runs.id (int).

        If no matching workflow_run exists, create one and cache the mapping
        so subsequent spawns within the same session reuse it.
        """
        from sqlalchemy import select

        from src.db import get_db
        from src.engine.run import create_run
        from src.models import WorkflowRun

        cache_key = context.run_id or ""

        if cache_key in self._run_id_cache:
            return self._run_id_cache[cache_key]

        if context.run_id:
            async with get_db() as session:
                result = await session.execute(
                    select(WorkflowRun.id).where(WorkflowRun.run_id == context.run_id)
                )
                row = result.scalar()
                if row is not None:
                    self._run_id_cache[cache_key] = row
                    return row

        run = await create_run(project_id=context.project_id or 0)
        # Patch run_id so future lookups within this session find it
        if context.run_id:
            async with get_db() as session:
                from src.models import WorkflowRun
                wf = await session.get(WorkflowRun, run.id)
                if wf is not None:
                    wf.run_id = context.run_id
                    await session.flush()
        self._run_id_cache[cache_key] = run.id
        return run.id
