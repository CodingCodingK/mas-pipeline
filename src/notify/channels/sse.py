"""In-memory per-user SSE fan-out channel.

Each connected SSE client calls `register(user_id)` to obtain a fresh
`asyncio.Queue`. `deliver` puts the notification on every queue registered
for that user (multi-tab / multi-device support). On full queue, the
oldest notification is dropped to make room for the new one.
"""

from __future__ import annotations

import asyncio
import logging
import time

from src.notify.events import Notification

logger = logging.getLogger(__name__)


class SseChannel:
    name = "sse"

    def __init__(self, default_max_size: int = 500) -> None:
        self._default_max_size = default_max_size
        self._queues: dict[int, list[asyncio.Queue]] = {}
        self._last_touched: dict[int, float] = {}

    def register(
        self, user_id: int, max_size: int | None = None
    ) -> asyncio.Queue:
        size = max_size if max_size is not None else self._default_max_size
        queue: asyncio.Queue = asyncio.Queue(maxsize=size)
        self._queues.setdefault(user_id, []).append(queue)
        self._last_touched[user_id] = time.monotonic()
        return queue

    def unregister(self, user_id: int, queue: asyncio.Queue) -> None:
        queues = self._queues.get(user_id)
        if not queues:
            return
        try:
            queues.remove(queue)
        except ValueError:
            return
        if not queues:
            self._queues.pop(user_id, None)
            self._last_touched.pop(user_id, None)

    async def deliver(self, notification: Notification) -> None:
        queues = self._queues.get(notification.user_id)
        if not queues:
            return
        self._last_touched[notification.user_id] = time.monotonic()
        for q in list(queues):
            try:
                q.put_nowait(notification)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(notification)
                except asyncio.QueueFull:
                    logger.warning(
                        "sse: queue still full after drop-oldest for user %d",
                        notification.user_id,
                    )

    async def cleanup_stale(self, idle_timeout_sec: float = 120.0) -> int:
        """Drop user queues untouched for longer than `idle_timeout_sec`.

        Returns the number of user entries removed. Intended to be called
        periodically by a background sweeper; does not itself schedule.
        """
        now = time.monotonic()
        stale = [
            uid
            for uid, ts in self._last_touched.items()
            if now - ts > idle_timeout_sec
        ]
        for uid in stale:
            self._queues.pop(uid, None)
            self._last_touched.pop(uid, None)
        return len(stale)
