"""list_projects — return active projects visible to clawbot."""

from __future__ import annotations

from sqlalchemy import select

from src.db import get_db
from src.models import Project
from src.tools.base import Tool, ToolContext, ToolResult


class ListProjectsTool(Tool):
    name = "list_projects"
    description = (
        "List active projects the user can run. Returns id, name, pipeline, "
        "and a short description for each project."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of projects to return (default 20)",
            },
        },
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        limit = int(params.get("limit") or 20)
        async with get_db() as session:
            result = await session.execute(
                select(Project)
                .where(Project.status == "active")
                .order_by(Project.id)
                .limit(limit)
            )
            rows = list(result.scalars().all())

        if not rows:
            return ToolResult(output="No active projects.", success=True)

        lines: list[str] = []
        for p in rows:
            desc = (p.description or "").strip().replace("\n", " ")
            if len(desc) > 120:
                desc = desc[:117] + "..."
            lines.append(f"#{p.id}  {p.name}  [pipeline={p.pipeline}]  {desc}")
        return ToolResult(output="\n".join(lines), success=True)
