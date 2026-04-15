"""confirm_pending_run — two-phase commit phase 2: launch the pipeline.

Reads the pending slot, creates a WorkflowRun row, fire-and-forgets
execute_pipeline() on its own asyncio.Task, and installs a
ChatProgressReporter in the Gateway-level registry so progress events
reach the chat channel. The reporter outlives the clawbot SessionRunner.

Physical isolation: execute_pipeline creates fresh AgentState per node
with history=[] (src/agent/factory.py:148), so the pipeline task shares
no mutable state with the clawbot conversation. The only connection is
the one-way EventBus → reporter → bus.publish_outbound path.
"""

from __future__ import annotations

import asyncio
import logging

from src.clawbot.reporter_registry import get_bus, register_reporter, unregister_reporter
from src.clawbot.session_state import get_pending_store
from src.db import get_db
from src.engine.run import create_run
from src.models import ChatSession
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ConfirmPendingRunTool(Tool):
    name = "confirm_pending_run"
    description = (
        "Launch the currently pending run for this chat. Only call when the "
        "user has affirmatively confirmed the staged request."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {},
    }

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        if context.session_id is None:
            return ToolResult(output="Error: no session_id on context", success=False)

        async with get_db() as session:
            chat_session = await session.get(ChatSession, context.session_id)
            if chat_session is None:
                return ToolResult(output="Error: chat session not found", success=False)
            session_key = chat_session.session_key
            channel = chat_session.channel
            chat_id = chat_session.chat_id
            conversation_id = chat_session.conversation_id

        store = get_pending_store()
        pending = store.get_pending(session_key)
        if pending is None:
            return ToolResult(
                output="No pending run to confirm (none staged or TTL expired).",
                success=False,
            )

        # Reserve the run_id in DB up-front so the reporter and pipeline
        # task agree on a single string identifier. workflow_runs.session_id
        # FKs to conversations(id), NOT chat_sessions(id) — pass the
        # conversation id, not the chat session primary key.
        run_row = await create_run(
            project_id=pending.project_id,
            session_id=conversation_id,
            pipeline=pending.pipeline,
        )
        pipeline_run_id = run_row.run_id

        store.clear_pending(session_key)

        bus = get_bus()
        if bus is None:
            logger.error(
                "confirm_pending_run: no MessageBus installed in reporter_registry"
            )
            return ToolResult(
                output="Error: progress reporting unavailable (bus not wired)",
                success=False,
            )

        from src.clawbot.progress_reporter import ChatProgressReporter

        reporter = ChatProgressReporter(
            run_id=pipeline_run_id,
            channel=channel,
            chat_id=chat_id,
            conversation_id=conversation_id,
            bus=bus,
            on_done=unregister_reporter,
        )
        register_reporter(pipeline_run_id, reporter)
        reporter.start()

        # Fire-and-forget pipeline task. Captured only for logging — the
        # reporter is the user-visible completion signal.
        asyncio.create_task(
            _run_pipeline_bg(
                pipeline=pending.pipeline,
                pipeline_run_id=pipeline_run_id,
                project_id=pending.project_id,
                inputs=pending.inputs,
            ),
            name=f"clawbot-pipeline:{pipeline_run_id}",
        )

        return ToolResult(
            output=(
                f"Launched pipeline '{pending.pipeline}' for project "
                f"#{pending.project_id} (run_id={pipeline_run_id}). Progress "
                f"will stream back as '[run #{pipeline_run_id}] ...' messages."
            ),
            success=True,
            metadata={"run_id": pipeline_run_id},
        )


async def _run_pipeline_bg(
    *,
    pipeline: str,
    pipeline_run_id: str,
    project_id: int,
    inputs: dict,
) -> None:
    from src.engine.pipeline import execute_pipeline

    try:
        user_input = inputs.get("user_input") if isinstance(inputs, dict) else None
        if not user_input:
            user_input = str(inputs)
        await execute_pipeline(
            pipeline_name=pipeline,
            run_id=pipeline_run_id,
            project_id=project_id,
            user_input=user_input,
        )
    except Exception:
        logger.exception(
            "clawbot pipeline run %s crashed (pipeline=%s)", pipeline_run_id, pipeline
        )
