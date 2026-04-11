"""Shared in-process event bus for fan-out to independent consumers."""

from src.events.bus import EventBus

__all__ = ["EventBus"]
