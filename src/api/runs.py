"""REST endpoints for workflow runs: trigger, resume, cancel, query."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from html import escape as html_escape
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from src.api.auth import require_api_key
from src.db import get_db
from src.engine.pipeline import execute_pipeline, resume_pipeline
from src.engine.run import (
    RunStatus,
    create_run,
    get_abort_signal,
    get_run,
    list_runs,
    subscribe_pipeline_events,
    unsubscribe_pipeline_events,
    update_run_status,
)
from src.agent.runs import get_agent_run, list_agent_runs
from src.models import AgentRun, WorkflowRun
from src.storage import resolve_pipeline_file

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


# ── Models ──────────────────────────────────────────────────


class TriggerRunBody(BaseModel):
    input: dict[str, Any] = {}


class TriggerRunResponse(BaseModel):
    run_id: str


class ResumeBody(BaseModel):
    """Accepts two resume shapes:

    1. Legacy bare-string: ``{"value": "feedback text"}`` — treated as an
       approve-with-comment. The engine's ``interrupt_fn`` silently drops
       the comment on approve, so this is effectively a plain approve.
    2. Structured: ``{"value": {"action": "approve"|"reject"|"edit",
       "feedback"?: str, "edited"?: str}}``. ``action=edit`` requires a
       non-empty ``edited`` field; validation below raises 422 otherwise.

    The API layer validates only the shape — semantic enforcement (e.g.
    ignoring ``feedback`` on approve) happens in ``_make_interrupt_fn``.
    """

    value: Any = None

    @field_validator("value")
    @classmethod
    def _validate_value(cls, v: Any) -> Any:
        if v is None or isinstance(v, str):
            return v
        if not isinstance(v, dict):
            raise ValueError(
                "value must be a string (legacy) or an object "
                "{action, feedback?, edited?}"
            )
        action = v.get("action", "approve")
        if action not in {"approve", "reject", "edit"}:
            raise ValueError(
                f"action must be one of approve/reject/edit, got {action!r}"
            )
        if action == "edit":
            edited = v.get("edited", "")
            if not isinstance(edited, str) or not edited.strip():
                raise ValueError(
                    "action=edit requires a non-empty 'edited' string field"
                )
        return v


class StatusResponse(BaseModel):
    run_id: str
    status: str


class RunListItem(BaseModel):
    run_id: str
    project_id: int
    pipeline: str | None = None
    status: str
    started_at: str | None = None
    finished_at: str | None = None


class RunListResponse(BaseModel):
    items: list[RunListItem]


class RunDetail(BaseModel):
    run_id: str
    project_id: int
    pipeline: str | None = None
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    outputs: dict[str, str] = {}
    final_output: str = ""
    error: str | None = None
    paused_at: str | None = None
    paused_output: str = ""


class AgentRunItem(BaseModel):
    id: int
    role: str
    description: str | None = None
    status: str
    owner: str | None = None
    result: str | None = None
    tool_use_count: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunItem]


class AgentRunDetail(BaseModel):
    """Full agent run record including transcript.

    Returned only by the single-id endpoint. The list endpoint deliberately
    excludes `messages` to avoid TOASTed JSONB reads for every row.
    """

    id: int
    run_id: int
    role: str
    description: str | None = None
    status: str
    owner: str | None = None
    result: str | None = None
    messages: list[dict] = []
    tool_use_count: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    created_at: str | None = None
    updated_at: str | None = None


# ── Helpers ─────────────────────────────────────────────────


def _to_list_item(run: WorkflowRun) -> RunListItem:
    return RunListItem(
        run_id=run.run_id,
        project_id=run.project_id,
        pipeline=run.pipeline,
        status=run.status,
        started_at=str(run.started_at) if run.started_at else None,
        finished_at=str(run.finished_at) if run.finished_at else None,
    )


def _to_detail(run: WorkflowRun) -> RunDetail:
    meta = run.metadata_ or {}
    return RunDetail(
        run_id=run.run_id,
        project_id=run.project_id,
        pipeline=run.pipeline,
        status=run.status,
        started_at=str(run.started_at) if run.started_at else None,
        finished_at=str(run.finished_at) if run.finished_at else None,
        outputs=meta.get("outputs", {}),
        final_output=meta.get("final_output", ""),
        error=meta.get("error"),
        paused_at=meta.get("paused_at"),
        paused_output=meta.get("paused_output", ""),
    )


def _user_input_from_dict(payload: dict[str, Any]) -> str:
    """Pipelines accept a single user_input str. Coerce dict→JSON for now."""
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False)


# ── Endpoints ───────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/pipelines/{pipeline_name}/runs",
    status_code=202,
)
async def trigger_pipeline(
    project_id: int,
    pipeline_name: str,
    body: TriggerRunBody,
    stream: bool = Query(False),
):
    """Create a WorkflowRun and start pipeline execution.

    `?stream=true` switches to an SSE response that emits status updates as
    the run progresses (Phase 6.1: status-only — full StreamEvent fan-out
    requires deeper engine surgery, tracked in deployment risks).
    """
    try:
        yaml_path = resolve_pipeline_file(pipeline_name, project_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"pipeline not found: {pipeline_name}"
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    run = await create_run(
        project_id=project_id,
        pipeline=pipeline_name,
    )
    user_input = _user_input_from_dict(body.input)

    # Resolve canonical pipeline name (strip _generation suffix for execute_pipeline)
    canonical = yaml_path.stem

    async def _do_run():
        try:
            await execute_pipeline(
                pipeline_name=canonical,
                run_id=run.run_id,
                project_id=project_id,
                user_input=user_input,
            )
        except Exception:
            logger.exception("Pipeline run %s crashed", run.run_id)

    if not stream:
        asyncio.create_task(_do_run(), name=f"pipeline:{run.run_id}")
        return TriggerRunResponse(run_id=run.run_id)

    # SSE: subscribe to the pipeline event stream BEFORE kicking off the
    # task, so we don't miss the pipeline_start event.
    queue = subscribe_pipeline_events(run.run_id)
    task = asyncio.create_task(_do_run(), name=f"pipeline:{run.run_id}")

    async def event_stream():
        from src.api.metrics import sse_connect, sse_disconnect
        sse_connect()
        try:
            yield (
                f"event: started\n"
                f"data: {json.dumps({'run_id': run.run_id})}\n\n"
            )
            terminal_types = {"pipeline_end", "pipeline_failed"}
            while True:
                # Periodic timeout lets us detect "pipeline crashed before
                # emitting end" via task.done() + drain remaining events.
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat to keep the connection alive through proxies.
                    yield ": ping\n\n"
                    if task.done() and queue.empty():
                        # Pipeline task is gone and no events pending — bail.
                        return
                    continue

                payload = json.dumps(
                    {"run_id": run.run_id, **event}, ensure_ascii=False
                )
                yield f"event: {event.get('type', 'message')}\ndata: {payload}\n\n"

                if event.get("type") in terminal_types:
                    return
        finally:
            unsubscribe_pipeline_events(run.run_id, queue)
            sse_disconnect()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: str, body: ResumeBody) -> StatusResponse:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != RunStatus.PAUSED.value:
        raise HTTPException(status_code=409, detail="run is not paused")
    if run.pipeline is None:
        raise HTTPException(status_code=409, detail="run has no pipeline associated")

    feedback = body.value

    async def _do_resume():
        try:
            await resume_pipeline(
                pipeline_name=run.pipeline,
                run_id=run.run_id,
                project_id=run.project_id,
                feedback=feedback,
            )
        except Exception:
            logger.exception("Pipeline resume %s crashed", run.run_id)

    asyncio.create_task(_do_resume(), name=f"pipeline-resume:{run.run_id}")
    return StatusResponse(run_id=run.run_id, status="resumed")


@router.post("/runs/{run_id}/pause", status_code=202)
async def pause_run(run_id: str) -> StatusResponse:
    """Request a running pipeline to pause at the next safe point.

    Flips the workflow row to ``paused`` and sets the shared abort_signal
    so in-flight LangGraph nodes can observe it on their next abort check.
    Idempotent against a run that is already paused. Note: an LLM call
    currently in-flight on a node runs to completion before the engine
    re-reads the signal — pause latency can be up to the node's turn.
    """
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    if run.status == RunStatus.PAUSED.value:
        return StatusResponse(run_id=run.run_id, status="paused")

    if run.status != RunStatus.RUNNING.value:
        raise HTTPException(
            status_code=409,
            detail=f"run is not running (current status: {run.status})",
        )

    signal = get_abort_signal(run.run_id)
    if signal is not None:
        signal.set()

    try:
        await update_run_status(run.run_id, RunStatus.PAUSED)
    except Exception:
        logger.exception("Failed to mark run %s paused", run.run_id)
        raise HTTPException(status_code=500, detail="failed to transition run state")

    return StatusResponse(run_id=run.run_id, status="paused")


@router.post("/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str) -> StatusResponse:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    # No-op if already in a terminal state.
    if run.status in (
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
    ):
        return StatusResponse(run_id=run.run_id, status=run.status)

    signal = get_abort_signal(run.run_id)
    if signal is not None:
        signal.set()

    try:
        await update_run_status(run.run_id, RunStatus.CANCELLED)
    except Exception:
        logger.exception("Failed to mark run %s cancelled", run.run_id)

    return StatusResponse(run_id=run.run_id, status="cancelled")


@router.get(
    "/projects/{project_id}/runs",
    response_model=RunListResponse,
)
async def list_project_runs(project_id: int) -> RunListResponse:
    """List all workflow runs for a project, newest first."""
    runs = await list_runs(project_id)
    return RunListResponse(items=[_to_list_item(r) for r in runs])


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run_detail(run_id: str) -> RunDetail:
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _to_detail(run)


class GraphNode(BaseModel):
    id: str
    name: str
    role: str
    output: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    output_preview: str | None = None


class GraphEdge(BaseModel):
    from_: str
    to: str
    kind: str = "sequence"

    model_config = {"populate_by_name": True}

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        d["from"] = d.pop("from_")
        return d


class RunGraphResponse(BaseModel):
    run_id: str
    pipeline: str | None
    status: str
    nodes: list[GraphNode]
    edges: list[dict]


def _map_node_status(
    agent_row_status: str | None,
    paused_at_node: str | None,
    this_node_name: str,
) -> str:
    """Map an agent_runs row status into the closed DAG status set.

    Paused-at-interrupt: if the pipeline's metadata.paused_at matches this
    node and the row is completed, upgrade the status to 'paused' (the run
    is held at this node's interrupt node awaiting human review).
    """
    if agent_row_status is None:
        return "idle"
    if paused_at_node == this_node_name and agent_row_status == "completed":
        return "paused"
    mapping = {
        "pending": "idle",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "skipped": "skipped",
        "timeout": "failed",
    }
    return mapping.get(agent_row_status, "idle")


@router.get("/runs/{run_id}/graph")
async def get_run_graph(run_id: str) -> dict:
    """Return the pipeline DAG joined with live agent_runs state.

    Pure read: no DB writes, no in-memory state mutation. Pipeline topology
    comes from the YAML on disk; per-node status comes from the agent_runs
    rows for this workflow_run. Nodes whose YAML definition has no matching
    row are reported as 'idle'.
    """
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    if run.pipeline is None:
        raise HTTPException(status_code=409, detail="run has no pipeline associated")

    try:
        yaml_path = resolve_pipeline_file(run.pipeline, run.project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"pipeline YAML unreadable: {exc}")

    from src.engine.pipeline import load_pipeline
    try:
        pipeline_def = load_pipeline(str(yaml_path))
    except Exception as exc:
        logger.exception("Failed to load pipeline for graph endpoint")
        raise HTTPException(status_code=500, detail=f"pipeline parse error: {exc}")

    agent_rows = await list_agent_runs(run.id)
    # owner is formatted as "{run_id_str}:{role}" for pipeline nodes; we
    # prefer matching by role since each pipeline node has a unique role.
    # Fall back: last row wins if multiple rows share the same role.
    by_role: dict[str, AgentRun] = {}
    for row in agent_rows:
        by_role[row.role] = row

    meta = run.metadata_ or {}
    outputs = meta.get("outputs", {}) or {}
    paused_at = meta.get("paused_at")

    nodes_out: list[GraphNode] = []
    for node in pipeline_def.nodes:
        row = by_role.get(node.role)
        status = _map_node_status(
            row.status if row else None, paused_at, node.name
        )
        preview: str | None = None
        raw_output = outputs.get(node.output)
        if isinstance(raw_output, str) and raw_output:
            preview = html_escape(raw_output)[:200]
        nodes_out.append(
            GraphNode(
                id=node.name,
                name=node.name,
                role=node.role,
                output=node.output,
                status=status,
                started_at=(str(row.created_at) if row and row.created_at else None),
                finished_at=(
                    str(row.updated_at)
                    if row and row.updated_at and row.status
                    in ("completed", "failed", "cancelled")
                    else None
                ),
                output_preview=preview,
            )
        )

    edges_out: list[dict] = []
    for node in pipeline_def.nodes:
        for upstream_name in pipeline_def.dependencies.get(node.name, set()):
            edges_out.append({"from": upstream_name, "to": node.name, "kind": "sequence"})
        for route in node.routes or []:
            edges_out.append({
                "from": node.name,
                "to": route.target,
                "kind": "conditional",
            })

    return {
        "run_id": run.run_id,
        "pipeline": run.pipeline,
        "status": run.status,
        "nodes": [n.model_dump() for n in nodes_out],
        "edges": edges_out,
    }


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str):
    """Standalone SSE endpoint for attaching to an already-running or paused
    pipeline. The initial trigger endpoint emits events only for its own
    request lifecycle; this endpoint lets the UI re-attach after navigation
    or after a resume transitions the run from paused → running again.

    The stream stays open until the run reaches a terminal state
    (pipeline_end or pipeline_failed). Heartbeats are sent every 15s so
    proxies don't idle-close the connection.
    """
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    terminal_db = (
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
    )
    if run.status in terminal_db:
        async def _immediate():
            yield (
                f"event: terminal\n"
                f"data: {json.dumps({'run_id': run.run_id, 'status': run.status})}\n\n"
            )
        return StreamingResponse(_immediate(), media_type="text/event-stream")

    queue = subscribe_pipeline_events(run.run_id)

    async def event_stream():
        from src.api.metrics import sse_connect, sse_disconnect
        sse_connect()
        terminal_types = {"pipeline_end", "pipeline_failed"}
        try:
            yield (
                f"event: attached\n"
                f"data: {json.dumps({'run_id': run.run_id, 'status': run.status})}\n\n"
            )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                payload = json.dumps(
                    {"run_id": run.run_id, **event}, ensure_ascii=False
                )
                yield f"event: {event.get('type', 'message')}\ndata: {payload}\n\n"
                if event.get("type") in terminal_types:
                    return
        finally:
            unsubscribe_pipeline_events(run.run_id, queue)
            sse_disconnect()

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


def build_paused_markdown(run: WorkflowRun, paused_node: str) -> tuple[str, str]:
    """Render a paused run's in-progress output (awaiting human review) as md.

    Returns ``(base_name, body)``. Reads ``workflow_runs.metadata_.paused_output``
    which ``execute_pipeline`` writes when it hits an ``interrupt: true`` node.
    Used by clawbot's pipeline_paused branch to attach the review material
    to the group chat notification.
    """
    meta = run.metadata_ or {}
    paused_output = meta.get("paused_output", "")
    pipeline_name = (run.pipeline or "run").replace("_generation", "")
    from datetime import datetime
    ts_part = datetime.utcnow().strftime("%Y%m%d_%H%M")
    base_name = f"{pipeline_name}_{paused_node}_paused_{ts_part}"
    body = paused_output if paused_output else "(paused node produced no output)"
    return base_name, body


def build_run_markdown(run: WorkflowRun, include_all: bool = False) -> tuple[str, str]:
    """Render a workflow run's final output as Markdown.

    Returns ``(base_name, body)``. ``base_name`` is the filename stem without
    extension: ``{pipeline}_result_{YYYYMMDD_HHMM}``. Reused by
    ``export_run`` (HTTP) and clawbot's chat attachment path so both stay
    in lockstep.
    """
    meta = run.metadata_ or {}
    outputs = meta.get("outputs", {})
    final_output = meta.get("final_output", "")

    pipeline_name = (run.pipeline or "run").replace("_generation", "")
    ts_part = ""
    if run.finished_at:
        ts_part = run.finished_at.strftime("%Y%m%d_%H%M")
    elif run.started_at:
        ts_part = run.started_at.strftime("%Y%m%d_%H%M")
    base_name = f"{pipeline_name}_result_{ts_part}" if ts_part else f"{pipeline_name}_result"

    if include_all:
        lines = [f"# {pipeline_name} Result\n"]
        for node_name, content in outputs.items():
            lines.append(f"## {node_name}\n\n{content}\n")
        if final_output and final_output not in outputs.values():
            lines.append(f"## Final Output\n\n{final_output}\n")
    else:
        lines = [final_output if final_output else "(no output)"]

    return base_name, "\n".join(lines)


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: str,
    fmt: str = Query("md"),
    include_all: bool = Query(False),
) -> StreamingResponse:
    """Export run result.

    By default exports only the final output. Set ``include_all=true``
    to include all intermediate node outputs as well.
    """
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    base_name, md_body = build_run_markdown(run, include_all=include_all)

    if fmt == "json":
        meta = run.metadata_ or {}
        payload: dict = {"run_id": run.run_id, "final_output": meta.get("final_output", "")}
        if include_all:
            payload["outputs"] = meta.get("outputs", {})
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{base_name}.json"'},
        )

    return StreamingResponse(
        iter([md_body]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{base_name}.md"'},
    )


def _to_agent_run_item(a: AgentRun) -> AgentRunItem:
    return AgentRunItem(
        id=a.id,
        role=a.role,
        description=a.description,
        status=a.status,
        owner=a.owner,
        result=a.result,
        tool_use_count=a.tool_use_count or 0,
        total_tokens=a.total_tokens or 0,
        duration_ms=a.duration_ms or 0,
        created_at=str(a.created_at) if a.created_at else None,
        updated_at=str(a.updated_at) if a.updated_at else None,
    )


@router.get("/runs/{run_id}/agents", response_model=AgentRunListResponse)
async def list_run_agents(run_id: str) -> AgentRunListResponse:
    """List all AgentRun records for a workflow run.

    Excludes the `messages` JSONB column for performance — use
    `GET /api/agent-runs/{id}` to fetch the full transcript for a single row.
    """
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    agents = await list_agent_runs(run.id)
    return AgentRunListResponse(items=[_to_agent_run_item(a) for a in agents])


@router.get("/agent-runs/{agent_run_id}", response_model=AgentRunDetail)
async def get_agent_run_detail(agent_run_id: int) -> AgentRunDetail:
    """Return the full AgentRun record including transcript + statistics.

    Used by analysis UIs (chat drawer, pipeline RunDetailPage drawer) to
    inspect a completed sub-agent post-hoc. Main-agent runtime SHALL NOT
    call this — it is frontend-only.
    """
    a = await get_agent_run(agent_run_id)
    if a is None:
        raise HTTPException(status_code=404, detail="agent run not found")
    return AgentRunDetail(
        id=a.id,
        run_id=a.run_id,
        role=a.role,
        description=a.description,
        status=a.status,
        owner=a.owner,
        result=a.result,
        messages=list(a.messages or []),
        tool_use_count=a.tool_use_count or 0,
        total_tokens=a.total_tokens or 0,
        duration_ms=a.duration_ms or 0,
        created_at=str(a.created_at) if a.created_at else None,
        updated_at=str(a.updated_at) if a.updated_at else None,
    )
