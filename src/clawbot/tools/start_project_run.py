"""start_project_run — two-phase commit phase 1: stash a pending run.

Does NOT launch the pipeline. Writes the request into the per-session
PendingRunStore (90s TTL, single-slot overwrite) and returns a
"waiting for confirmation" message. The user's next message decides:
  - confirmation → confirm_pending_run launches the pipeline
  - cancellation → cancel_pending_run clears the slot
  - modification → another start_project_run overwrites

Single-slot overwrite returns the previous pending (if any) so the LLM
can broadcast "A's request was replaced by B's".

Same-turn double-call guard: if this tool is called twice in the same
agent turn, only the first wins — the second returns an error. The guard
uses a context-local flag keyed by run_id (clawbot's SessionRunner run_id,
not the pipeline run_id).
"""

from __future__ import annotations

import logging
from typing import Any

from src.clawbot.session_state import PendingRun, get_pending_store
from src.db import get_db
from src.models import ChatSession, Project
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

_turn_guard: dict[str, bool] = {}


def _turn_key(context: ToolContext) -> str:
    return f"{context.run_id or 'na'}:{context.session_id or 'na'}"


def reset_turn_guard_for_tests() -> None:
    _turn_guard.clear()


def clear_turn_guard(context: ToolContext) -> None:
    """Call at agent-turn boundary to allow a fresh start_project_run."""
    _turn_guard.pop(_turn_key(context), None)


class StartProjectRunTool(Tool):
    name = "start_project_run"
    description = (
        "Stage a pipeline run for user confirmation. Does NOT launch the "
        "pipeline immediately. Returns a 'pending confirmation' marker; the "
        "run only starts after confirm_pending_run() is called."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "integer",
                "description": "Numeric project id to run.",
            },
            "inputs": {
                "type": "object",
                "description": "Pipeline user_input / params object.",
            },
            "pipeline": {
                "type": "string",
                "description": (
                    "Optional pipeline name. Omit to use the project's "
                    "default pipeline."
                ),
            },
        },
        "required": ["project_id", "inputs"],
    }

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        key = _turn_key(context)
        if _turn_guard.get(key):
            return ToolResult(
                output=(
                    "Error: start_project_run already called in this turn. "
                    "Only one pending run may be staged per turn."
                ),
                success=False,
            )

        try:
            project_id = int(params["project_id"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(output="Error: project_id must be an integer", success=False)

        inputs = params.get("inputs") or {}
        if not isinstance(inputs, dict):
            return ToolResult(output="Error: inputs must be an object", success=False)

        pipeline_override = params.get("pipeline")

        if context.session_id is None:
            return ToolResult(
                output="Error: clawbot session not found (no session_id on context)",
                success=False,
            )

        async with get_db() as session:
            proj = await session.get(Project, project_id)
            if proj is None:
                return ToolResult(output=f"Project #{project_id} not found", success=False)
            chat_session = await session.get(ChatSession, context.session_id)
            if chat_session is None:
                return ToolResult(
                    output="Error: chat session not found",
                    success=False,
                )
            session_key = chat_session.session_key
            pipeline = pipeline_override or proj.pipeline
            project_name = proj.name

        pending = PendingRun(
            project_id=project_id,
            pipeline=pipeline,
            inputs=_shallow_json_safe(inputs),
            initiator_sender_id=None,
        )
        previous = get_pending_store().set_pending(session_key, pending)
        _turn_guard[key] = True

        lines = [
            f"Pending run staged (awaiting confirmation, 90s TTL):",
            f"  project: #{project_id} {project_name}",
            f"  pipeline: {pipeline}",
            f"  inputs: {pending.inputs}",
            "",
            "Ask the user to confirm (y/yes/ok/跑吧/确认) or cancel.",
        ]
        if previous is not None:
            lines.insert(
                0,
                (
                    f"⚠️  Previous pending run replaced "
                    f"(was project #{previous.project_id} / {previous.pipeline})."
                ),
            )
        return ToolResult(output="\n".join(lines), success=True)


def _shallow_json_safe(obj: Any) -> dict:
    """Coerce top-level inputs to a JSON-serializable dict."""
    try:
        import json
        json.dumps(obj)
        return obj
    except TypeError:
        return {k: repr(v) for k, v in (obj or {}).items()}
