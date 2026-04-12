"""REST endpoints for workflow runs: trigger, resume, cancel, query."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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
from src.agent.runs import list_agent_runs
from src.models import WorkflowRun
from src.storage import resolve_pipeline_file

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


# ── Models ──────────────────────────────────────────────────


class TriggerRunBody(BaseModel):
    input: dict[str, Any] = {}


class TriggerRunResponse(BaseModel):
    run_id: str


class ResumeBody(BaseModel):
    value: Any = None


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


class AgentRunItem(BaseModel):
    id: int
    role: str
    description: str | None = None
    status: str
    owner: str | None = None
    result: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunItem]


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


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: str,
    fmt: str = Query("md"),
    include_all: bool = Query(False),
) -> StreamingResponse:
    """Export run result.

    By default exports only the final output. Set ``include_all=true``
    to include all intermediate node outputs as well.

    Filename: ``{pipeline}_result_{datetime}.{ext}`` unless the pipeline
    input specified a custom ``title``.
    """
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    meta = run.metadata_ or {}
    outputs = meta.get("outputs", {})
    final_output = meta.get("final_output", "")

    # Build filename: pipeline_result_YYYYMMDD_HHMM
    pipeline_name = (run.pipeline or "run").replace("_generation", "")
    ts_part = ""
    if run.finished_at:
        ts_part = run.finished_at.strftime("%Y%m%d_%H%M")
    elif run.started_at:
        ts_part = run.started_at.strftime("%Y%m%d_%H%M")
    base_name = f"{pipeline_name}_result_{ts_part}" if ts_part else f"{pipeline_name}_result"

    if fmt == "json":
        payload: dict = {"run_id": run.run_id, "final_output": final_output}
        if include_all:
            payload["outputs"] = outputs
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([body]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{base_name}.json"'},
        )

    # Markdown: only final output by default
    if include_all:
        lines = [f"# {pipeline_name} Result\n"]
        for node_name, content in outputs.items():
            lines.append(f"## {node_name}\n\n{content}\n")
        if final_output and final_output not in outputs.values():
            lines.append(f"## Final Output\n\n{final_output}\n")
    else:
        lines = [final_output if final_output else "(no output)"]

    body = "\n".join(lines)
    return StreamingResponse(
        iter([body]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{base_name}.md"'},
    )


@router.get("/runs/{run_id}/agents", response_model=AgentRunListResponse)
async def list_run_agents(run_id: str) -> AgentRunListResponse:
    """List all AgentRun records for a workflow run."""
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    agents = await list_agent_runs(run.id)
    return AgentRunListResponse(
        items=[
            AgentRunItem(
                id=a.id,
                role=a.role,
                description=a.description,
                status=a.status,
                owner=a.owner,
                result=a.result,
                created_at=str(a.created_at) if a.created_at else None,
                updated_at=str(a.updated_at) if a.updated_at else None,
            )
            for a in agents
        ]
    )
