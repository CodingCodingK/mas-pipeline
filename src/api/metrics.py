"""Prometheus-format operational metrics.

Exposes 5 collectors at /metrics (root prefix, unauthenticated):
  sessions_active       gauge   — SessionRunner registry size
  workers_running       gauge   — in-flight jobs + in-flight sub-agent workers
  pg_connections_used   gauge   — SQLAlchemy pool checked-out count
  sse_connections       gauge   — open SSE long-poll connections
  messages_total        counter — cumulative event-bus emit count

Gauges are pulled from live registries via `set_function` callbacks so the
value at scrape time is always derived from the source of truth — no drift
from missed inc/dec calls.
"""

from __future__ import annotations

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

# ── Collectors ───────────────────────────────────────────────
# Kept at module level so imports are idempotent and the WSGI layer can call
# generate_latest() directly without threading state.

sessions_active = Gauge(
    "sessions_active", "Number of currently-registered SessionRunner instances"
)
workers_running = Gauge(
    "workers_running", "Number of in-flight agent workers and running jobs"
)
pg_connections_used = Gauge(
    "pg_connections_used",
    "Connections currently checked out from the SQLAlchemy pool",
)
sse_connections = Gauge(
    "sse_connections", "Open SSE long-poll connections across all endpoints"
)
messages_total = Counter(
    "messages_total", "Cumulative events emitted on the internal event bus"
)


# ── SSE connection tracking ──────────────────────────────────
# SSE handlers call inc()/dec() from their try/finally. The global counter
# is the source of truth for the sse_connections gauge.

_sse_open_count: int = 0


def sse_connect() -> None:
    global _sse_open_count
    _sse_open_count += 1


def sse_disconnect() -> None:
    global _sse_open_count
    if _sse_open_count > 0:
        _sse_open_count -= 1


def _sse_current() -> int:
    return _sse_open_count


# ── Wiring ───────────────────────────────────────────────────


def setup_metrics() -> None:
    """Bind gauge callbacks to live registries and the DB engine.

    Safe to call once at app startup, after the engine and registries exist.
    Idempotent — repeated calls overwrite the same callbacks.
    """
    from src.db import get_engine
    from src.engine import session_registry
    from src.jobs import get_registry as get_jobs_registry

    def _sessions() -> float:
        return float(len(session_registry.snapshot()))

    def _workers() -> float:
        # Running jobs + running sub-agent count across all active runners.
        running_jobs = sum(1 for j in get_jobs_registry().list() if j.status == "running")
        running_subs = 0
        for runner in session_registry.snapshot():
            state = getattr(runner, "state", None)
            if state is not None:
                running_subs += getattr(state, "running_agent_count", 0)
        return float(running_jobs + running_subs)

    def _pg_used() -> float:
        try:
            return float(get_engine().pool.checkedout())
        except Exception:
            return 0.0

    sessions_active.set_function(_sessions)
    workers_running.set_function(_workers)
    pg_connections_used.set_function(_pg_used)
    sse_connections.set_function(lambda: float(_sse_current()))


# ── Endpoint ────────────────────────────────────────────────


async def metrics_endpoint() -> Response:
    """Return the full Prometheus text exposition."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
