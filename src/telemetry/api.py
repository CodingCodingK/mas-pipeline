"""Telemetry REST API: 10 endpoints for run / session / project queries.

All endpoints require the standard API key dependency. Missing resources
return 404. The reload-pricing admin endpoint triggers an atomic swap of
the collector's pricing table.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.auth import require_api_key
from src.telemetry import get_collector
from src.telemetry.query import (
    get_project_aggregate,
    get_project_cost,
    get_project_trends,
    get_run_agents,
    get_run_errors,
    get_run_summary,
    get_run_timeline,
    get_run_tree,
    get_session_agents,
    get_session_summary,
    get_session_timeline,
    get_session_tree,
    list_project_sessions,
    list_project_turns,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", dependencies=[Depends(require_api_key)])


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


# ── Run-scoped ────────────────────────────────────────────


@router.get("/runs/{run_id}/summary")
async def run_summary(run_id: str) -> dict[str, Any]:
    try:
        return await get_run_summary(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{run_id}/timeline")
async def run_timeline(run_id: str) -> list[dict[str, Any]]:
    try:
        return await get_run_timeline(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{run_id}/tree")
async def run_tree(run_id: str) -> dict[str, Any]:
    try:
        return await get_run_tree(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{run_id}/agents")
async def run_agents(run_id: str) -> list[dict[str, Any]]:
    try:
        return await get_run_agents(run_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/runs/{run_id}/errors")
async def run_errors(run_id: str) -> list[dict[str, Any]]:
    return await get_run_errors(run_id)


# ── Session-scoped ────────────────────────────────────────


@router.get("/sessions/{session_id}/summary")
async def session_summary(session_id: int) -> dict[str, Any]:
    try:
        return await get_session_summary(session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/sessions/{session_id}/tree")
async def session_tree(session_id: int) -> dict[str, Any]:
    try:
        return await get_session_tree(session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/sessions/{session_id}/timeline")
async def session_timeline(session_id: int) -> list[dict[str, Any]]:
    try:
        return await get_session_timeline(session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get("/sessions/{session_id}/agents")
async def session_agents(session_id: int) -> list[dict[str, Any]]:
    try:
        return await get_session_agents(session_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


# ── Project-scoped ────────────────────────────────────────


@router.get("/projects/{project_id}/cost")
async def project_cost(
    project_id: int,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    group_by: str = Query(default="day", pattern="^(day|run|pipeline)$"),
    pipeline: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    return await get_project_cost(
        project_id=project_id,
        from_=from_,
        to_=to,
        group_by=group_by,
        pipeline=pipeline,
    )


@router.get("/projects/{project_id}/trends")
async def project_trends(
    project_id: int,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> dict[str, Any]:
    return await get_project_trends(project_id=project_id, from_=from_, to_=to)


# ── Observability Tab (project-scoped lists) ─────────────


async def _assert_project_exists(project_id: int) -> None:
    """404 if project_id is supplied but no matching project row exists."""
    from sqlalchemy import text as _text
    from src.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            _text("SELECT 1 FROM projects WHERE id = :pid"),
            {"pid": project_id},
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="project not found")


@router.get("/sessions")
async def observability_sessions(
    project_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    """List chat sessions; when ``project_id`` is omitted, returns all."""
    if project_id is not None:
        await _assert_project_exists(project_id)
    return await list_project_sessions(
        project_id=project_id, limit=limit, offset=offset
    )


@router.get("/aggregate")
async def observability_aggregate(
    project_id: int | None = Query(default=None),
    window: str = Query(default="24h", pattern="^(24h|7d|30d)$"),
) -> dict[str, Any]:
    """Bucketed aggregate for the Observability Tab Aggregates sub-tab."""
    if project_id is not None:
        await _assert_project_exists(project_id)
    return await get_project_aggregate(project_id=project_id, window=window)


@router.get("/turns")
async def observability_turns(
    project_id: int | None = Query(default=None),
    role: str | None = Query(default=None),
    status: str | None = Query(
        default=None, pattern="^(done|interrupt|error|idle_exit)$"
    ),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Recent agent_turn events with role/status filters."""
    if project_id is not None:
        await _assert_project_exists(project_id)
    return await list_project_turns(
        project_id=project_id, role=role, status=status, limit=limit
    )


# ── Admin ────────────────────────────────────────────────


admin_router = APIRouter(
    prefix="/admin/telemetry", dependencies=[Depends(require_api_key)]
)


@admin_router.post("/reload-pricing")
async def reload_pricing() -> dict[str, Any]:
    count = get_collector().reload_pricing()
    return {"models_loaded": count}
