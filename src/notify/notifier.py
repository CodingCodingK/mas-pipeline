"""Notifier: bus consumer → rules → per-user channel dispatch.

Subscribes to the shared `EventBus` as `"notify"`, drains its queue in a
background task, runs each event through the configured rule set, looks up
each matched notification's user preferences, and fan-outs to the enabled
channels. Every rule and channel call is guarded — one failure never
poisons the loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from sqlalchemy import text

from src.events.bus import EventBus
from src.notify import preferences
from src.notify.channels.base import Channel
from src.notify.events import Notification
from src.notify.rules import Rule, default_rules
from src.telemetry.events import TelemetryEvent

logger = logging.getLogger(__name__)

UserResolver = Callable[[int], Awaitable["int | None"]]


def make_project_user_resolver(session_factory) -> UserResolver:
    """Build a cached async resolver from `project_id` to `user_id`.

    Ownership of a project rarely changes, so we memoize in-process. A bad
    lookup returns None and is NOT cached (so a later insert will be picked up).
    """
    cache: dict[int, int] = {}

    async def resolve(project_id: int) -> int | None:
        if project_id in cache:
            return cache[project_id]
        if project_id <= 0:
            return None
        try:
            async with session_factory() as session:
                result = await session.execute(
                    text("SELECT user_id FROM projects WHERE id = :pid"),
                    {"pid": project_id},
                )
                row = result.first()
        except Exception:
            logger.exception("notify: failed to resolve user for project %d", project_id)
            return None
        if row is None:
            return None
        user_id = int(row[0])
        cache[project_id] = user_id
        return user_id

    return resolve


class Notifier:
    def __init__(
        self,
        *,
        bus: EventBus,
        channels: list[Channel],
        rules: list[Rule] | None,
        session_factory,
        resolve_user: UserResolver | None = None,
        queue_size: int = 5000,
    ) -> None:
        self._bus = bus
        self.channels: list[Channel] = list(channels)
        self._rules: list[Rule] = list(rules) if rules is not None else default_rules()
        self._session_factory = session_factory
        self._resolve_user: UserResolver = (
            resolve_user
            if resolve_user is not None
            else make_project_user_resolver(session_factory)
        )
        self._queue: asyncio.Queue = bus.subscribe("notify", max_size=queue_size)
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="notify-loop")
        logger.info(
            "notify: started (channels=%s, rules=%d)",
            [c.name for c in self.channels], len(self._rules),
        )

    async def stop(self, timeout_seconds: float = 5.0) -> None:
        if self._task is None:
            return
        self._stopping.set()
        self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=timeout_seconds)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception:
            logger.exception("notify: loop raised during stop")
        self._task = None
        # Best-effort close webhook channels.
        for ch in self.channels:
            close = getattr(ch, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    logger.exception("notify: channel %s close failed", ch.name)

    # ── Main loop ──────────────────────────────────────────────────

    async def _loop(self) -> None:
        try:
            while not self._stopping.is_set():
                try:
                    event = await self._queue.get()
                except asyncio.CancelledError:
                    raise
                try:
                    await self._handle_event(event)
                except Exception:
                    logger.exception("notify: unhandled error processing event")
        except asyncio.CancelledError:
            return

    async def _handle_event(self, event: object) -> None:
        if not isinstance(event, TelemetryEvent):
            return
        user_id = await self._resolve_user(event.project_id)
        if user_id is None:
            return

        for rule in self._rules:
            try:
                notification = rule(event, user_id)
            except Exception:
                logger.warning(
                    "notify: rule %s raised", getattr(rule, "__name__", rule),
                    exc_info=True,
                )
                continue
            if notification is None:
                continue
            await self._dispatch(notification)

    async def _dispatch(self, notification: Notification) -> None:
        try:
            enabled = await preferences.get(
                notification.user_id, notification.event_type, self._session_factory
            )
        except Exception:
            logger.exception(
                "notify: failed to load preferences for user %d", notification.user_id
            )
            return
        if not enabled:
            logger.debug(
                "notify: user %d has no channels for %s, dropping",
                notification.user_id, notification.event_type,
            )
            return
        enabled_set = set(enabled)
        for channel in self.channels:
            if channel.name not in enabled_set:
                continue
            try:
                await channel.deliver(notification)
            except Exception:
                logger.warning(
                    "notify: channel %s deliver failed for notification %s",
                    channel.name, notification.notification_id, exc_info=True,
                )


class NullNotifier(Notifier):
    """No-op notifier. Used when `notify.enabled=false` in settings."""

    def __init__(self, bus: EventBus | None = None) -> None:  # noqa: D401
        self._bus = bus
        self.channels = []
        self._rules = []
        self._session_factory = None

        async def _null_resolve(_pid: int) -> int | None:
            return None

        self._resolve_user = _null_resolve
        self._queue = asyncio.Queue(maxsize=1)
        self._task = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        return None

    async def stop(self, timeout_seconds: float = 5.0) -> None:
        return None


_global_notifier: Notifier | None = None


def set_notifier(notifier: Notifier) -> None:
    global _global_notifier
    _global_notifier = notifier


def get_notifier() -> Notifier:
    global _global_notifier
    if _global_notifier is None:
        _global_notifier = NullNotifier()
    return _global_notifier
