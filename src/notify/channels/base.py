"""Channel protocol: name + async deliver."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.notify.events import Notification


@runtime_checkable
class Channel(Protocol):
    name: str

    async def deliver(self, notification: Notification) -> None: ...
