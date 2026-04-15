"""Project-info tools: read-only introspection for top-level chat agents.

Three tools, all scoped to `ToolContext.project_id` (never accepting a
`project_id` param from the LLM):

- ``get_current_project`` — name / pipeline / doc_count / latest run for
  the project bound to ``ToolContext``. Distinct from clawbot's
  ``get_project_info`` which takes an explicit ``project_id`` and is used
  by the group-chat router to describe a project it doesn't own.
- ``list_project_runs`` — recent workflow_runs with status filter + limit.
- ``get_run_details``   — one run's agent_runs breakdown with preview.

Cross-project reads are structurally impossible: every query's WHERE clause
includes ``project_id = context.project_id``. ``get_run_details`` collapses
"missing run" and "wrong project" into a single not-found response so the
agent never learns that a run exists in another project.
"""

from __future__ import annotations

from src.tools.base import Tool, ToolContext, ToolResult

_NO_PROJECT_ERROR = "Error: no project context available"
_PREVIEW_MAX_CHARS = 200


def _fmt_dt(dt) -> str:
    """Format a datetime for tool output. Returns '-' for None."""
    return str(dt) if dt is not None else "-"


def _compute_duration_seconds(started, finished) -> str:
    """Return seconds-as-int string, or '-' if either timestamp is missing."""
    if started is None or finished is None:
        return "-"
    delta = finished - started
    return str(int(delta.total_seconds()))


def _extract_last_assistant_preview(messages: list, fallback_result: str | None) -> str:
    """Pull the last assistant message text from an agent_runs.messages JSONB.

    Fallback chain: last assistant text → agent_runs.result → "(no output)".
    Truncated to _PREVIEW_MAX_CHARS with a trailing ellipsis if cut.
    """
    text: str | None = None
    if isinstance(messages, list):
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                text = content
                break
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text")
                        if isinstance(t, str):
                            parts.append(t)
                joined = "".join(parts).strip()
                if joined:
                    text = joined
                    break

    if not text:
        text = (fallback_result or "").strip() or None
    if not text:
        text = "(no output)"

    if len(text) > _PREVIEW_MAX_CHARS:
        text = text[:_PREVIEW_MAX_CHARS] + "…"
    return text.replace("\n", " ")


class GetCurrentProjectTool(Tool):
    name = "get_current_project"
    description = (
        "Return the current project's metadata: name, bound pipeline, "
        "document count, and the most recent run's status. Takes no "
        "parameters — always describes the project bound to this session. "
        "Use when the user asks about 'my project', 'what pipeline', "
        "'how many documents', or similar project-scoped questions."
    )
    input_schema: dict = {"type": "object", "properties": {}, "required": []}

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    def is_read_only(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        if context.project_id is None:
            return ToolResult(output=_NO_PROJECT_ERROR, success=False)

        from sqlalchemy import func, select

        from src.db import get_db
        from src.models import Document, Project, WorkflowRun

        pid = context.project_id
        async with get_db() as session:
            proj = await session.get(Project, pid)
            if proj is None:
                return ToolResult(
                    output=f"Error: project {pid} not found", success=False
                )

            doc_count_row = await session.execute(
                select(func.count(Document.id)).where(Document.project_id == pid)
            )
            doc_count = int(doc_count_row.scalar() or 0)

            latest_row = await session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == pid)
                .order_by(
                    WorkflowRun.started_at.desc().nullslast(),
                    WorkflowRun.id.desc(),
                )
                .limit(1)
            )
            latest: WorkflowRun | None = latest_row.scalar_one_or_none()

        lines = [
            f"project_id: {proj.id}",
            f"name: {proj.name}",
            f"pipeline: {proj.pipeline}",
        ]
        if proj.description:
            lines.append(f"description: {proj.description}")
        lines.append(f"document_count: {doc_count}")
        if latest is None:
            lines.append("latest_run: (none)")
        else:
            lines.append(
                f"latest_run: {latest.run_id} | {latest.status} | "
                f"{_fmt_dt(latest.started_at)}"
            )
        return ToolResult(output="\n".join(lines))


class ListProjectRunsTool(Tool):
    name = "list_project_runs"
    description = (
        "List recent workflow runs for the current project, newest first. "
        "Optional `status` filter (e.g. 'completed', 'failed', 'running'). "
        "Use this to answer 'what runs did I do', 'show failed runs', etc."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max number of runs to return (1-50, default 10).",
            },
            "status": {
                "type": "string",
                "description": "Optional exact-match status filter (completed / failed / running / pending).",
            },
        },
        "required": [],
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    def is_read_only(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        if context.project_id is None:
            return ToolResult(output=_NO_PROJECT_ERROR, success=False)

        raw_limit = params.get("limit", 10)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(50, limit))

        status_filter = params.get("status")
        if status_filter is not None and not isinstance(status_filter, str):
            status_filter = None

        from sqlalchemy import select

        from src.db import get_db
        from src.models import WorkflowRun

        pid = context.project_id
        async with get_db() as session:
            stmt = select(WorkflowRun).where(WorkflowRun.project_id == pid)
            if status_filter:
                stmt = stmt.where(WorkflowRun.status == status_filter)
            stmt = stmt.order_by(
                WorkflowRun.started_at.desc().nullslast(),
                WorkflowRun.id.desc(),
            ).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

        if not rows:
            return ToolResult(output="(no runs)")

        lines = []
        for r in rows:
            duration = _compute_duration_seconds(r.started_at, r.finished_at)
            lines.append(
                f"{r.run_id} | {r.pipeline or '-'} | {r.status} | "
                f"{_fmt_dt(r.started_at)} | {duration}s"
            )
        return ToolResult(output="\n".join(lines))


class GetRunDetailsTool(Tool):
    name = "get_run_details"
    description = (
        "Return per-node breakdown of a single workflow run (must belong to "
        "the current project). Lists each agent's role, status, tool count, "
        "tokens, duration, and a short preview of the final output. Use after "
        "list_project_runs to drill into a specific run."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "The string run identifier (matches workflow_runs.run_id).",
            },
        },
        "required": ["run_id"],
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    def is_read_only(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        if context.project_id is None:
            return ToolResult(output=_NO_PROJECT_ERROR, success=False)

        rid = params.get("run_id")
        if not isinstance(rid, str) or not rid.strip():
            return ToolResult(
                output="Error: run_id is required", success=False
            )

        from sqlalchemy import select

        from src.db import get_db
        from src.models import AgentRun, WorkflowRun

        pid = context.project_id
        async with get_db() as session:
            row = await session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.run_id == rid,
                    WorkflowRun.project_id == pid,
                )
            )
            run: WorkflowRun | None = row.scalar_one_or_none()
            if run is None:
                return ToolResult(
                    output=f"Error: run '{rid}' not found in current project",
                    success=False,
                )

            agents_row = await session.execute(
                select(AgentRun)
                .where(AgentRun.run_id == run.id)
                .order_by(AgentRun.id.asc())
            )
            agents = agents_row.scalars().all()

        duration_s = _compute_duration_seconds(run.started_at, run.finished_at)
        header = (
            f"run_id: {run.run_id} | pipeline: {run.pipeline or '-'} | "
            f"status: {run.status} | duration: {duration_s}s"
        )
        if not agents:
            return ToolResult(output=f"{header}\n(no nodes)")

        lines = [header]
        for a in agents:
            preview = _extract_last_assistant_preview(a.messages, a.result)
            lines.append(
                f"{a.role} | {a.status} | tools={a.tool_use_count or 0} | "
                f"tokens={a.total_tokens or 0} | {a.duration_ms or 0}ms | {preview}"
            )
        return ToolResult(output="\n".join(lines))
