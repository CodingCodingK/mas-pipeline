"""Global registry of in-process SessionRunner instances.

Phase 6.1: dict + lock + factory + lookup + shutdown_all + idle GC sweeper
+ PG LISTEN session_wakeup forwarder.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.session_runner import SessionRunner

logger = logging.getLogger(__name__)

# How often the idle GC sweeper runs (seconds).
_GC_INTERVAL_SECONDS = 60


_session_runners: dict[int, SessionRunner] = {}
_registry_lock: asyncio.Lock = asyncio.Lock()


async def get_or_create_runner(
    session_id: int,
    mode: str,
    project_id: int,
    conversation_id: int,
) -> tuple[SessionRunner, bool]:
    """Idempotent factory. Returns (runner, created) — *created* is True when
    a brand-new runner was started in this call.

    Callers must check *created*: a freshly started runner already picks up
    pending PG messages via ``_sync_inbound_from_pg``, so calling
    ``notify_new_message()`` on it would cause a spurious second wakeup and
    a duplicate response.

    The lock is held only during dict mutation. SessionRunner construction
    (which awaits create_agent) happens outside the lock to avoid blocking
    other registry callers.
    """
    from src.engine.session_runner import SessionRunner

    # Fast path under lock
    async with _registry_lock:
        existing = _session_runners.get(session_id)
        if existing is not None and not existing.is_done:
            return existing, False

    # Construct outside the lock (may await)
    runner = SessionRunner(
        session_id=session_id,
        mode=mode,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    await runner.start()

    # Re-acquire lock and check again — concurrent caller may have raced.
    async with _registry_lock:
        existing = _session_runners.get(session_id)
        if existing is not None and not existing.is_done:
            # Lost the race — discard ours and return the winner.
            await runner.request_exit()
            return existing, False
        _session_runners[session_id] = runner
        return runner, True


def get_runner(session_id: int) -> SessionRunner | None:
    """Lookup; no lock needed for a single dict.get."""
    return _session_runners.get(session_id)


async def deregister(session_id: int) -> None:
    """Called by SessionRunner's finally block on exit."""
    async with _registry_lock:
        _session_runners.pop(session_id, None)


def snapshot() -> list[SessionRunner]:
    """Return a list copy of current runners (safe to iterate while mutating)."""
    return list(_session_runners.values())


async def shutdown_all(timeout_seconds: float = 5.0) -> None:
    """Graceful shutdown — set wakeup on all runners, await up to timeout each.
    Cancel stragglers.
    """
    runners = snapshot()
    logger.info("Shutting down %d SessionRunner(s)", len(runners))
    for r in runners:
        await r.request_exit()
    for r in runners:
        try:
            await asyncio.wait_for(r.wait_done(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("SessionRunner %d did not exit in %.1fs, cancelling", r.session_id, timeout_seconds)
            r.cancel()


# ── Idle GC sweeper ─────────────────────────────────────────


async def _idle_gc_task() -> None:
    """Background loop: every 60s sweep registry, request_exit on stale runners.

    A runner is "stale" when:
    - 0 subscribers AND 0 running sub-agents AND idle for >= idle_timeout, OR
    - alive longer than max_age regardless of activity.

    The actual exit is performed by the runner itself in its main loop —
    GC just nudges via request_exit().
    """
    from src.project.config import get_settings

    logger.info("session_registry: idle GC task started")
    try:
        while True:
            await asyncio.sleep(_GC_INTERVAL_SECONDS)
            try:
                settings = get_settings()
                idle_timeout = timedelta(seconds=settings.session.idle_timeout_seconds)
                max_age = timedelta(seconds=settings.session.max_age_seconds)
                now = datetime.utcnow()

                for runner in snapshot():
                    if runner.is_done:
                        continue
                    age = now - runner.created_at
                    idle = now - runner.last_active_at
                    has_subs = len(runner.subscribers) > 0
                    has_workers = (
                        runner.state is not None
                        and runner.state.running_agent_count > 0
                    )
                    if age >= max_age:
                        logger.info(
                            "GC: SessionRunner %d exceeded max_age, requesting exit",
                            runner.session_id,
                        )
                        await runner.request_exit()
                    elif (
                        not has_subs
                        and not has_workers
                        and idle >= idle_timeout
                    ):
                        logger.info(
                            "GC: SessionRunner %d idle %.0fs, requesting exit",
                            runner.session_id, idle.total_seconds(),
                        )
                        await runner.request_exit()
            except Exception:
                logger.exception("session_registry: GC sweep crashed (will retry)")
    except asyncio.CancelledError:
        logger.info("session_registry: idle GC task cancelled")
        raise


# ── PG LISTEN session_wakeup forwarder ──────────────────────


async def _listen_session_wakeup() -> None:
    """Background loop: LISTEN session_wakeup on a dedicated PG connection,
    forward NOTIFY payloads to the local registry.

    Forward-compat for multi-process deployments — in single-process mode the
    in-process wakeup path already covers everything, but the listener still
    runs so a NOTIFY from this process is harmless (idempotent set()).
    """
    import psycopg

    from src.db import _pg_conn_string

    conn = None
    try:
        conn = await psycopg.AsyncConnection.connect(
            _pg_conn_string(), autocommit=True
        )
        await conn.execute("LISTEN session_wakeup")
        logger.info("session_registry: LISTEN session_wakeup task started")

        gen = conn.notifies()
        async for notify in gen:
            try:
                session_id = int(notify.payload)
            except (ValueError, TypeError):
                logger.warning(
                    "session_registry: ignoring NOTIFY with non-int payload: %r",
                    notify.payload,
                )
                continue
            runner = get_runner(session_id)
            if runner is not None:
                runner.notify_new_message()
    except asyncio.CancelledError:
        logger.info("session_registry: LISTEN task cancelled")
        raise
    except Exception:
        logger.exception("session_registry: LISTEN task crashed")
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
