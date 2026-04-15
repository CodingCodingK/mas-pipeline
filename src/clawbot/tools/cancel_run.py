"""cancel_run — abort a running or paused pipeline run.

Mirrors the semantics of ``POST /api/runs/{run_id}/cancel``:

- Flips the in-process abort signal so an executing pipeline coroutine
  cooperatively exits at the next checkpoint.
- Transitions ``workflow_runs.status`` to ``cancelled``.

Scope note: distinct from ``cancel_pending_run`` (which clears a 10-min
pending slot that never turned into a real run). This tool targets runs
that already have a ``workflow_runs`` row.
"""

from __future__ import annotations

import logging

from src.engine.run import (
    RunStatus,
    get_abort_signal,
    get_run,
    update_run_status,
)
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

_TERMINAL = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}


class CancelRunTool(Tool):
    name = "cancel_run"
    description = (
        "Cancel a running or paused pipeline run by its run_id. Use when "
        "the user explicitly asks to stop / abort / kill a run that has "
        "already started. Does NOT apply to pending (unconfirmed) runs — "
        "use cancel_pending_run for those."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Pipeline run_id to cancel.",
            },
        },
        "required": ["run_id"],
    }

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        run_id = (params.get("run_id") or "").strip()
        if not run_id:
            return ToolResult(output="Error: run_id cannot be empty", success=False)

        run = await get_run(run_id)
        if run is None:
            return ToolResult(output=f"Run {run_id} not found", success=False)

        if run.status in _TERMINAL:
            return ToolResult(
                output=f"Run {run_id} is already {run.status}; nothing to cancel.",
                success=True,
            )

        signal = get_abort_signal(run_id)
        if signal is not None:
            signal.set()

        try:
            await update_run_status(run_id, RunStatus.CANCELLED)
        except Exception:
            logger.exception("cancel_run: failed to mark %s cancelled", run_id)
            return ToolResult(
                output=f"Error: failed to mark run {run_id} cancelled",
                success=False,
            )

        return ToolResult(
            output=f"Run {run_id} cancelled.",
            success=True,
            metadata={"run_id": run_id},
        )
