"""Job dataclass for tracking long-running async tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "failed"]

_QUEUE_MAX_SIZE = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    """A tracked long-running task with progress queue.

    The queue is a 1:1 channel — only one consumer (the SSE endpoint) reads
    from it. `emit` is fire-and-forget for the producer; on a full queue
    the oldest event is dropped to make room.

    Lifecycle:
      pending → running (on first non-terminal emit)
              → done    (on emit({"event": "done", ...}))
              → failed  (on emit({"event": "failed", "error": ...}))
    Terminal events also enqueue a None sentinel so the SSE consumer can
    detect end-of-stream.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = "generic"
    status: JobStatus = "pending"
    error: str | None = None
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None
    last_event: dict | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX_SIZE))

    def emit(self, event: dict) -> None:
        """Push a progress event into the queue with drop-oldest on full.

        Updates `status`, `last_event`, `error`, `finished_at` based on the
        event type. On terminal events (`done`/`failed`), also enqueues
        a `None` sentinel to signal end-of-stream to the SSE consumer.
        """
        event_type = event.get("event")

        # Status transitions
        if self.status == "pending" and event_type not in (None, "done", "failed"):
            self.status = "running"

        if event_type == "done":
            self.status = "done"
            self.finished_at = _now()
        elif event_type == "failed":
            self.status = "failed"
            self.finished_at = _now()
            self.error = event.get("error")

        self.last_event = event
        self._put_drop_oldest(event)

        # Sentinel for end-of-stream
        if event_type in ("done", "failed"):
            self._put_drop_oldest(None)

    def _put_drop_oldest(self, item: dict | None) -> None:
        """put_nowait with drop-oldest on full queue."""
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            try:
                _ = self.queue.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning("Job %s queue still full after drop-oldest; event lost", self.id)

    def to_dict(self) -> dict:
        """Serializable representation for `GET /api/jobs/{id}` (excludes queue)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "last_event": self.last_event,
        }
