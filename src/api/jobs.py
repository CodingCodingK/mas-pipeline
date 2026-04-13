"""REST endpoints for job status and SSE progress streaming."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.auth import require_api_key
from src.jobs import Job, get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", dependencies=[Depends(require_api_key)])


_HEARTBEAT_INTERVAL_SEC = 30.0


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    job = get_registry().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


def _terminal_replay_event(job: Job) -> dict:
    """Build a single event describing the terminal state of a finished job."""
    if job.last_event is not None:
        return job.last_event
    if job.status == "done":
        return {"event": "done"}
    if job.status == "failed":
        return {"event": "failed", "error": job.error if job.error is not None else ""}
    return {"event": job.status}


def _sse_frame(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def _stream_job_events(job: Job, request: Request) -> AsyncIterator[str]:
    """Yield SSE frames for a job until sentinel or client disconnect.
    Heartbeats keep proxies from closing idle connections."""
    # Fast path: already finished — replay last_event then close.
    if job.status in ("done", "failed"):
        yield _sse_frame("progress", _terminal_replay_event(job))
        return

    while True:
        if await request.is_disconnected():
            return

        try:
            item = await asyncio.wait_for(
                job.queue.get(), timeout=_HEARTBEAT_INTERVAL_SEC
            )
        except asyncio.TimeoutError:
            yield _sse_frame("heartbeat", {})
            continue

        if item is None:
            # Sentinel — finished; close the stream.
            return

        yield _sse_frame("progress", item)


@router.get("/{job_id}/stream")
async def stream_job(job_id: str, request: Request) -> StreamingResponse:
    job = get_registry().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return StreamingResponse(
        _stream_job_events(job, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
