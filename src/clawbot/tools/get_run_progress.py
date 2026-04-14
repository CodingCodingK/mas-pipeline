"""get_run_progress — look up current state of a pipeline run."""

from __future__ import annotations

from src.engine.run import get_run
from src.tools.base import Tool, ToolContext, ToolResult


class GetRunProgressTool(Tool):
    name = "get_run_progress"
    description = (
        "Look up the current status of a pipeline run by its run_id. "
        "Use when the user asks about a run in progress."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Pipeline run_id as emitted by start_project_run/confirm.",
            },
        },
        "required": ["run_id"],
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        run_id = (params.get("run_id") or "").strip()
        if not run_id:
            return ToolResult(output="Error: run_id cannot be empty", success=False)

        run = await get_run(run_id)
        if run is None:
            return ToolResult(output=f"Run {run_id} not found", success=False)

        lines = [
            f"run_id: {run.run_id}",
            f"project_id: {run.project_id}",
            f"pipeline: {run.pipeline or '(none)'}",
            f"status: {run.status}",
            f"started_at: {run.started_at.isoformat() if run.started_at else '(unset)'}",
            f"finished_at: {run.finished_at.isoformat() if run.finished_at else '(unset)'}",
        ]
        return ToolResult(output="\n".join(lines), success=True)
