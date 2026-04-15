"""ClawBot per-session state: pending_run slot with TTL, stored in process memory.

Multi-worker deployment is not supported (Phase 8's WEB_CONCURRENCY hard-fail
guards this). Restart loss is acceptable — pending entries are short-lived
intent records, not durable state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 600.0


@dataclass
class PendingRun:
    """One pending project_run waiting for user confirmation."""

    project_id: int
    pipeline: str
    inputs: dict[str, Any]
    initiator_sender_id: str | None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def summary(self) -> str:
        age = (datetime.utcnow() - self.created_at).total_seconds()
        return (
            f"project_id: {self.project_id}\n"
            f"pipeline: {self.pipeline}\n"
            f"inputs: {self.inputs}\n"
            f"initiator: {self.initiator_sender_id or '(unknown)'}\n"
            f"age_seconds: {int(age)}"
        )


@dataclass
class PausedRun:
    """One pipeline run that's currently paused at an interrupt node.

    Tracked per-chat so clawbot can resolve natural-language resume intent
    ("打回 <理由>" / "通过") against the right run_id without the user
    typing `/resume <id>` every time. No TTL — lifecycle is driven by
    ChatProgressReporter seeing pipeline_end / pipeline_failed events.
    """

    run_id: str
    pipeline: str
    project_id: int
    paused_node: str
    paused_at_ts: datetime = field(default_factory=datetime.utcnow)

    def summary(self) -> str:
        age = (datetime.utcnow() - self.paused_at_ts).total_seconds()
        return (
            f"run_id: {self.run_id}\n"
            f"pipeline: {self.pipeline}\n"
            f"project_id: {self.project_id}\n"
            f"paused_node: {self.paused_node}\n"
            f"age_seconds: {int(age)}"
        )


@dataclass
class ClawbotSession:
    """Per-session_key clawbot state."""

    session_key: str
    pending_run: PendingRun | None = None
    paused_runs: dict[str, PausedRun] = field(default_factory=dict)
    _ttl_handle: asyncio.TimerHandle | None = None


class PendingRunStore:
    """Process-local store of clawbot sessions keyed by session_key."""

    def __init__(self) -> None:
        self._sessions: dict[str, ClawbotSession] = {}

    def get_session(self, session_key: str) -> ClawbotSession:
        sess = self._sessions.get(session_key)
        if sess is None:
            sess = ClawbotSession(session_key=session_key)
            self._sessions[session_key] = sess
        return sess

    def get_pending(self, session_key: str) -> PendingRun | None:
        sess = self._sessions.get(session_key)
        return sess.pending_run if sess is not None else None

    def set_pending(self, session_key: str, pending: PendingRun) -> PendingRun | None:
        """Store a pending entry, overwriting any existing one. Returns the
        previous pending (if any) so callers can broadcast a "replaced" notice.
        """
        sess = self.get_session(session_key)
        previous = sess.pending_run
        if sess._ttl_handle is not None:
            sess._ttl_handle.cancel()
            sess._ttl_handle = None
        sess.pending_run = pending
        try:
            loop = asyncio.get_running_loop()
            sess._ttl_handle = loop.call_later(
                PENDING_TTL_SECONDS, self._expire, session_key
            )
        except RuntimeError:
            logger.warning(
                "PendingRunStore.set_pending called outside event loop; "
                "no TTL scheduled for %s",
                session_key,
            )
        return previous

    def clear_pending(self, session_key: str) -> PendingRun | None:
        """Clear pending and cancel TTL. Returns the cleared entry (if any)."""
        sess = self._sessions.get(session_key)
        if sess is None:
            return None
        cleared = sess.pending_run
        sess.pending_run = None
        if sess._ttl_handle is not None:
            sess._ttl_handle.cancel()
            sess._ttl_handle = None
        return cleared

    # ── paused_runs ───────────────────────────────────────────────

    def set_paused(self, session_key: str, paused: PausedRun) -> None:
        """Register a paused run for this chat. Overwrites any entry with
        the same run_id (idempotent on repeated pipeline_paused events)."""
        sess = self.get_session(session_key)
        sess.paused_runs[paused.run_id] = paused

    def clear_paused(self, session_key: str, run_id: str) -> PausedRun | None:
        sess = self._sessions.get(session_key)
        if sess is None:
            return None
        return sess.paused_runs.pop(run_id, None)

    def list_paused(self, session_key: str) -> list[PausedRun]:
        sess = self._sessions.get(session_key)
        if sess is None:
            return []
        return list(sess.paused_runs.values())

    def get_paused(self, session_key: str, run_id: str) -> PausedRun | None:
        sess = self._sessions.get(session_key)
        if sess is None:
            return None
        return sess.paused_runs.get(run_id)

    def _expire(self, session_key: str) -> None:
        sess = self._sessions.get(session_key)
        if sess is None or sess.pending_run is None:
            return
        logger.info(
            "PendingRunStore: pending for %s expired after TTL", session_key
        )
        sess.pending_run = None
        sess._ttl_handle = None


_store: PendingRunStore | None = None


def get_pending_store() -> PendingRunStore:
    """Return the process-local singleton."""
    global _store
    if _store is None:
        _store = PendingRunStore()
    return _store


def reset_pending_store_for_tests() -> None:
    """Test helper — drop the singleton so each test starts fresh."""
    global _store
    if _store is not None:
        for sess in list(_store._sessions.values()):
            if sess._ttl_handle is not None:
                sess._ttl_handle.cancel()
    _store = None
