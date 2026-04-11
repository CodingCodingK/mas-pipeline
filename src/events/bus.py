"""In-process fan-out event bus with per-subscriber queue isolation.

Design
------
- Each `subscribe(name)` returns a fresh `asyncio.Queue` owned by the caller.
- `emit(event)` is synchronous O(n_subscribers): iterates subscribers and does
  `put_nowait` on each. Never awaits, never blocks business code.
- On a full subscriber queue, drops the oldest event and enqueues the new one,
  logging a rate-limited WARNING (at most 1 per 10s per subscriber).
- `close()` marks the bus closed; subsequent `emit` is a no-op. Pre-close events
  already on subscriber queues remain drainable.
- The bus owns no `asyncio.Task`. Consumers run their own loops.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_WARN_COOLDOWN_SEC = 10.0


class _Subscriber:
    __slots__ = ("name", "queue", "drop_count", "last_warn_at")

    def __init__(self, name: str, queue: asyncio.Queue) -> None:
        self.name = name
        self.queue = queue
        self.drop_count = 0
        self.last_warn_at = 0.0


class EventBus:
    """Synchronous fan-out router. Each subscriber owns its own queue + task."""

    def __init__(self, queue_size: int = 10000) -> None:
        self._default_queue_size = queue_size
        self._subscribers: list[_Subscriber] = []
        self._closed = False

    def subscribe(
        self, name: str, max_size: int | None = None
    ) -> asyncio.Queue:
        """Create and return a fresh queue for a new subscriber.

        The returned queue is owned by the caller. The caller must start its
        own consumer task that reads from the queue. Calling `subscribe` twice
        with the same name creates two independent subscribers.
        """
        size = max_size if max_size is not None else self._default_queue_size
        queue: asyncio.Queue = asyncio.Queue(maxsize=size)
        self._subscribers.append(_Subscriber(name=name, queue=queue))
        return queue

    def emit(self, event: object) -> None:
        """Fan the event out to every subscriber. Synchronous, O(n_subscribers).

        Never awaits. On full queue, drops oldest and enqueues new, logging a
        rate-limited WARNING. Never raises into the caller.
        """
        if self._closed:
            return
        for sub in self._subscribers:
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    # Shouldn't happen after a get_nowait, but be defensive.
                    continue
                sub.drop_count += 1
                now = time.monotonic()
                if now - sub.last_warn_at >= _WARN_COOLDOWN_SEC:
                    logger.warning(
                        "event_bus: subscriber %r dropped %d events since last warning",
                        sub.name,
                        sub.drop_count,
                    )
                    sub.drop_count = 0
                    sub.last_warn_at = now

    def close(self) -> None:
        """Mark the bus closed. Subsequent `emit` calls are no-ops."""
        self._closed = True
