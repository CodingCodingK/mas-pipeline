"""get_project_info — fetch detailed info for one project by explicit id."""

from __future__ import annotations

import json

from src.db import get_db
from src.models import Project
from src.tools.base import Tool, ToolContext, ToolResult


class GetProjectInfoTool(Tool):
    name = "get_project_info"
    description = (
        "Fetch one project's full detail (name, pipeline, config, status) "
        "by its numeric id. project_id is explicit — do NOT rely on session state."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "integer",
                "description": "Numeric project id as returned by list_projects.",
            },
        },
        "required": ["project_id"],
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        try:
            project_id = int(params["project_id"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(output="Error: project_id must be an integer", success=False)

        async with get_db() as session:
            proj = await session.get(Project, project_id)

        if proj is None:
            return ToolResult(output=f"Project #{project_id} not found", success=False)

        config_preview = json.dumps(proj.config or {}, ensure_ascii=False)[:500]
        body = (
            f"id: {proj.id}\n"
            f"name: {proj.name}\n"
            f"pipeline: {proj.pipeline}\n"
            f"status: {proj.status}\n"
            f"description: {(proj.description or '').strip()}\n"
            f"config: {config_preview}"
        )
        return ToolResult(output=body, success=True)
