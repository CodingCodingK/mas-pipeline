"""resume_run — clawbot natural-language resume for paused pipeline runs.

Companion to the `/resume` bus command: where that command is a dry
literal syntax the user has to type, this tool lets clawbot translate
natural-language review intent ("通过" / "打回，加 A 社分析" / "改成 ...")
into the right `Command(resume=...)` payload. The gateway's `/resume`
path still works as a fallback for power users.

Dispatch contract matches the REST /runs/{id}/resume handler — we fire
`resume_pipeline` as a detached task so the clawbot turn returns
immediately; progress_reporter is already subscribed to this run's event
stream and will emit the next pause / done / fail to chat.

Only runs registered in the per-chat paused store are addressable, so a
user in one group can never steer another group's pipeline via this
tool (cross-chat isolation is by construction).
"""

from __future__ import annotations

import asyncio
import logging

from src.clawbot.session_state import get_pending_store
from src.db import get_db
from src.models import ChatSession
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class ResumeRunTool(Tool):
    name = "resume_run"
    description = (
        "Resume a paused pipeline run in this chat with a natural-language "
        "review decision. Use when a `[Paused Run Awaiting Review]` block "
        "appears in your user-message head and the user expresses an "
        "outcome.\n\n"
        "Map user intent to `action`:\n"
        "  - 通过 / approve / 同意 / 可以 / ok → action=\"approve\"\n"
        "  - 打回 / 拒绝 / reject + 理由 → action=\"reject\", feedback=<用户原话>\n"
        "  - 改成 / 替换为 + 新文本 → action=\"edit\", edited=<新文本>\n\n"
        "`run_id` MUST come from the paused block — never invent one. If "
        "more than one run is paused and the user didn't say which, ask "
        "before calling this tool. For `reject` and `edit`, preserve the "
        "user's exact wording verbatim; do not paraphrase."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": (
                    "ID of the paused run to resume. Must match a run_id "
                    "listed in the [Paused Run Awaiting Review] block."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["approve", "reject", "edit"],
                "description": (
                    "Review outcome. approve = continue, reject = loop "
                    "back with feedback, edit = overwrite this node's "
                    "output with `edited` and continue."
                ),
            },
            "feedback": {
                "type": "string",
                "description": (
                    "Required for action=reject. The user's reason for "
                    "rejection, verbatim. Ignored for other actions."
                ),
            },
            "edited": {
                "type": "string",
                "description": (
                    "Required for action=edit. The replacement text to "
                    "write into the paused node's output, verbatim. "
                    "Ignored for other actions."
                ),
            },
        },
        "required": ["run_id", "action"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return False

    def is_read_only(self, params: dict) -> bool:
        return False

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        if context.session_id is None:
            return ToolResult(
                output="Error: no session_id on context", success=False
            )

        run_id = params.get("run_id")
        action = params.get("action")
        if not isinstance(run_id, str) or not run_id:
            return ToolResult(
                output="Error: run_id must be a non-empty string", success=False
            )
        if action not in ("approve", "reject", "edit"):
            return ToolResult(
                output=(
                    "Error: action must be one of 'approve' / 'reject' / 'edit'"
                ),
                success=False,
            )

        feedback_text = params.get("feedback") or ""
        edited_text = params.get("edited") or ""
        if action == "reject" and not feedback_text.strip():
            return ToolResult(
                output=(
                    "Error: action='reject' requires a non-empty `feedback` "
                    "with the user's reason verbatim."
                ),
                success=False,
            )
        if action == "edit" and not edited_text.strip():
            return ToolResult(
                output=(
                    "Error: action='edit' requires a non-empty `edited` "
                    "with the replacement text verbatim."
                ),
                success=False,
            )

        async with get_db() as session:
            chat_session = await session.get(ChatSession, context.session_id)
            if chat_session is None:
                return ToolResult(
                    output="Error: chat session not found", success=False
                )
            session_key = chat_session.session_key

        store = get_pending_store()
        paused = store.get_paused(session_key, run_id)
        if paused is None:
            # Hard isolation: a run this chat never saw paused can't be
            # resumed through here. The LLM likely hallucinated the run_id
            # or the run already finished.
            return ToolResult(
                output=(
                    f"Error: run_id {run_id!r} is not paused in this chat. "
                    "Check the [Paused Run Awaiting Review] block for valid "
                    "run_ids, or ask the user to confirm."
                ),
                success=False,
            )

        feedback_payload: dict = {"action": action}
        if action == "reject":
            feedback_payload["feedback"] = feedback_text
        elif action == "edit":
            feedback_payload["edited"] = edited_text

        # Ensure a progress reporter is subscribed so that the next
        # pause/done/fail streams back to chat. Normally the reporter
        # created by confirm_pending_run is still alive, but after a
        # gateway restart the in-memory registry is empty. Re-create
        # the reporter in that case so the user gets completion feedback.
        from src.clawbot.reporter_registry import (
            get_bus,
            get_reporter,
            register_reporter,
            unregister_reporter,
        )

        if get_reporter(run_id) is None:
            bus = get_bus()
            if bus is not None:
                from src.clawbot.progress_reporter import ChatProgressReporter

                reporter = ChatProgressReporter(
                    run_id=run_id,
                    channel=context.channel or "",
                    chat_id=context.chat_id or "",
                    conversation_id=context.conversation_id or 0,
                    bus=bus,
                    on_done=unregister_reporter,
                )
                register_reporter(run_id, reporter)
                reporter.start()

        asyncio.create_task(
            _resume_bg(
                pipeline=paused.pipeline,
                run_id=run_id,
                project_id=paused.project_id,
                feedback=feedback_payload,
            ),
            name=f"clawbot-resume:{run_id}",
        )

        human_action = {
            "approve": "通过",
            "reject": "打回",
            "edit": "改写",
        }[action]
        return ToolResult(
            output=(
                f"已触发 run #{run_id} {human_action}。进度会继续流回群里。"
            ),
            success=True,
            metadata={"run_id": run_id, "action": action},
        )


async def _resume_bg(
    *,
    pipeline: str,
    run_id: str,
    project_id: int,
    feedback: dict,
) -> None:
    from src.engine.pipeline import resume_pipeline

    try:
        await resume_pipeline(
            pipeline_name=pipeline,
            run_id=run_id,
            project_id=project_id,
            feedback=feedback,
        )
    except Exception:
        logger.exception(
            "clawbot resume_run bg task crashed (run_id=%s)", run_id
        )
