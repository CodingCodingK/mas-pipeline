"""cancel_pending_run — clear the session's pending_run slot."""

from __future__ import annotations

from src.clawbot.session_state import get_pending_store
from src.db import get_db
from src.models import ChatSession
from src.tools.base import Tool, ToolContext, ToolResult


class CancelPendingRunTool(Tool):
    name = "cancel_pending_run"
    description = (
        "Discard the currently pending run for this chat. Call when the user "
        "indicates cancellation (no/算了/取消)."
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

        cleared = get_pending_store().clear_pending(session_key)
        if cleared is None:
            return ToolResult(output="No pending run to cancel.", success=True)
        return ToolResult(
            output=(
                f"Cancelled pending run (project #{cleared.project_id}, "
                f"pipeline {cleared.pipeline})."
            ),
            success=True,
        )
