"""Workflow run management: CRUD + state machine + Redis sync."""

from __future__ import annotations

import asyncio
import logging
import uuid
from enum import Enum

from sqlalchemy import func, select

from src.db import get_db, get_redis
from src.models import WorkflowRun

logger = logging.getLogger(__name__)


# ── In-process abort signal registry ────────────────────────
# Lets POST /api/runs/{run_id}/cancel signal a pipeline coroutine that's
# currently executing in this process. Single-process only — multi-worker
# deployments need a different mechanism (see deployment risks plan).

_abort_signals: dict[str, asyncio.Event] = {}


def register_abort_signal(run_id: str, signal: asyncio.Event) -> None:
    _abort_signals[run_id] = signal


def get_abort_signal(run_id: str) -> asyncio.Event | None:
    return _abort_signals.get(run_id)


def unregister_abort_signal(run_id: str) -> None:
    _abort_signals.pop(run_id, None)


# ── In-process pipeline event stream registry ───────────────
# Lets the SSE trigger endpoint subscribe to lifecycle events emitted by
# `execute_pipeline` / graph node functions in the same process. Like
# `_abort_signals`, this is single-process only — multi-worker deployments
# would need PG NOTIFY or Redis pub/sub. See deployment risks plan.
#
# Each run_id maps to a list of subscriber queues. Emitters fan out to all
# subscribers; if a queue is full we silently drop (slow consumers shouldn't
# back-pressure the pipeline). When a subscriber disconnects it removes its
# own queue via `unsubscribe_pipeline_events`.

_pipeline_event_streams: dict[str, list[asyncio.Queue]] = {}
_PIPELINE_EVENT_QUEUE_MAX = 200


def subscribe_pipeline_events(run_id: str) -> asyncio.Queue:
    """Register a new subscriber for the run; returns the queue to drain."""
    q: asyncio.Queue = asyncio.Queue(maxsize=_PIPELINE_EVENT_QUEUE_MAX)
    _pipeline_event_streams.setdefault(run_id, []).append(q)
    return q


def unsubscribe_pipeline_events(run_id: str, q: asyncio.Queue) -> None:
    subs = _pipeline_event_streams.get(run_id)
    if not subs:
        return
    if q in subs:
        subs.remove(q)
    if not subs:
        _pipeline_event_streams.pop(run_id, None)


def emit_pipeline_event(run_id: str, event: dict) -> None:
    """Best-effort fan-out — never blocks, never raises.

    Drops the event for any subscriber whose queue is full (slow client) so
    pipeline progress is never blocked by SSE consumers.
    """
    subs = _pipeline_event_streams.get(run_id)
    if not subs:
        return
    for q in list(subs):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "pipeline event queue full for run %s, dropped %s",
                run_id, event.get("type", "?"),
            )
        except Exception:
            logger.exception("emit_pipeline_event failed for run %s", run_id)


# ── State machine ──────────────────────────────────────────


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


VALID_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.PAUSED,
        RunStatus.CANCELLED,
    },
    RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    # COMPLETED, FAILED, CANCELLED are terminal — no outgoing transitions
}

_TERMINAL_STATES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


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


async def update_run_status(
    run_id: str,
    status: RunStatus,
    *,
    result_payload: dict | None = None,
) -> WorkflowRun:
    """Update a workflow run's status with state machine validation.

    When `result_payload` is provided, it is shallow-merged into
    `WorkflowRun.metadata_` inside the same session as the status transition.
    The merge reassigns a fresh dict so SQLAlchemy flushes the JSONB column;
    an in-place `dict.update` would be silently dropped at flush time.

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
        if result_payload is not None:
            existing = run.metadata_ or {}
            run.metadata_ = {**existing, **result_payload}

    await _sync_to_redis(run)
    return run


async def finish_run(
    run_id: str,
    status: RunStatus,
    *,
    result_payload: dict | None = None,
) -> WorkflowRun:
    """Set a workflow run to a terminal state with finished_at.

    When `result_payload` is provided, it is shallow-merged into
    `WorkflowRun.metadata_` atomically with the status transition and
    finished_at write.

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
        if result_payload is not None:
            existing = run.metadata_ or {}
            run.metadata_ = {**existing, **result_payload}
        await session.flush()
        await session.refresh(run)

    await _sync_to_redis(run)
    return run
