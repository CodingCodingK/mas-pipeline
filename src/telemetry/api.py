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
    get_project_cost,
    get_project_trends,
    get_run_agents,
    get_run_errors,
    get_run_summary,
    get_run_timeline,
    get_run_tree,
    get_session_summary,
    get_session_tree,
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


# ── Admin ────────────────────────────────────────────────


admin_router = APIRouter(
    prefix="/admin/telemetry", dependencies=[Depends(require_api_key)]
)


@admin_router.post("/reload-pricing")
async def reload_pricing() -> dict[str, Any]:
    count = get_collector().reload_pricing()
    return {"models_loaded": count}
