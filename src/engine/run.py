"""Workflow run management: CRUD + state machine + Redis sync."""

from __future__ import annotations

import logging
import uuid
from enum import Enum

from sqlalchemy import func, select

from src.db import get_db, get_redis
from src.models import WorkflowRun

logger = logging.getLogger(__name__)


# ── State machine ──────────────────────────────────────────


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


VALID_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING},
    RunStatus.RUNNING: {RunStatus.COMPLETED, RunStatus.FAILED},
    # COMPLETED and FAILED are terminal — no outgoing transitions
}

_TERMINAL_STATES = {RunStatus.COMPLETED, RunStatus.FAILED}


class InvalidTransitionError(Exception):
    """Raised when a status transition violates the state machine."""


def _validate_transition(current: str, target: RunStatus) -> None:
    try:
        current_status = RunStatus(current)
    except ValueError:
        raise InvalidTransitionError(
            f"Unknown current status '{current}'"
        ) from None

    allowed = VALID_TRANSITIONS.get(current_status, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from '{current_status.value}' to '{target.value}'. "
            f"Allowed: {sorted(s.value for s in allowed) if allowed else '(terminal state)'}"
        )


# ── Redis sync ─────────────────────────────────────────────


async def _sync_to_redis(run: WorkflowRun) -> None:
    """Write run state to Redis Hash for fast lookups."""
    redis = get_redis()
    key = f"workflow_run:{run.run_id}"
    fields: dict[str, str] = {
        "project_id": str(run.project_id),
        "pipeline": run.pipeline or "",
        "status": run.status,
        "started_at": str(run.started_at) if run.started_at else "",
        "finished_at": str(run.finished_at) if run.finished_at else "",
    }
    await redis.hset(key, mapping=fields)


# ── CRUD ───────────────────────────────────────────────────


async def create_run(
    project_id: int,
    session_id: int | None = None,
    pipeline: str | None = None,
) -> WorkflowRun:
    """Create a new workflow run.

    Generates a unique run_id (UUID-based), sets status='pending' and started_at=now().
    Syncs initial state to Redis.
    """
    run = WorkflowRun(
        project_id=project_id,
        session_id=session_id,
        run_id=uuid.uuid4().hex[:16],
        pipeline=pipeline,
        status=RunStatus.PENDING.value,
        started_at=func.now(),
    )
    async with get_db() as session:
        session.add(run)
        await session.flush()
        # Refresh to get server-generated started_at
        await session.refresh(run)

    await _sync_to_redis(run)
    return run


async def get_run(run_id: str) -> WorkflowRun | None:
    """Get a workflow run by its unique run_id string."""
    async with get_db() as session:
        result = await session.execute(
            select(WorkflowRun).where(WorkflowRun.run_id == run_id)
        )
        return result.scalars().first()


async def list_runs(project_id: int) -> list[WorkflowRun]:
    """List all workflow runs for a project, newest first."""
    async with get_db() as session:
        result = await session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id)
            .order_by(WorkflowRun.id.desc())
        )
        return list(result.scalars().all())


async def update_run_status(run_id: str, status: RunStatus) -> WorkflowRun:
    """Update a workflow run's status with state machine validation.

    Raises InvalidTransitionError if the transition is not allowed.
    Raises ValueError if run_id not found.
    """
    async with get_db() as session:
        result = await session.execute(
            select(WorkflowRun).where(WorkflowRun.run_id == run_id)
        )
        run = result.scalars().first()
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found")

        _validate_transition(run.status, status)
        run.status = status.value

    await _sync_to_redis(run)
    return run


async def finish_run(run_id: str, status: RunStatus) -> WorkflowRun:
    """Set a workflow run to a terminal state with finished_at.

    Only COMPLETED and FAILED are accepted. Raises ValueError otherwise.
    Raises InvalidTransitionError if the transition is not allowed.
    """
    if status not in _TERMINAL_STATES:
        raise ValueError(
            f"finish_run only accepts terminal states ({', '.join(s.value for s in _TERMINAL_STATES)}), "
            f"got '{status.value}'"
        )

    async with get_db() as session:
        result = await session.execute(
            select(WorkflowRun).where(WorkflowRun.run_id == run_id)
        )
        run = result.scalars().first()
        if run is None:
            raise ValueError(f"Workflow run '{run_id}' not found")

        _validate_transition(run.status, status)
        run.status = status.value
        run.finished_at = func.now()
        await session.flush()
        await session.refresh(run)

    await _sync_to_redis(run)
    return run
