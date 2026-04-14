"""Process-local registry of live ChatProgressReporter instances.

Ownership: the Gateway initializes this at startup via `install_registry`
and cancels all live reporters on shutdown. Tools (`confirm_pending_run`)
call `register_reporter` to add a new reporter when a pipeline run is
launched; the reporter removes itself via `unregister_reporter` from its
on_done callback.

A reporter outlives the SessionRunner that spawned it because runs commonly
run past a session's idle window (decision P4). Keeping the registry on
the Gateway (not the runner) enforces that invariant.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.bus.bus import MessageBus
    from src.clawbot.progress_reporter import ChatProgressReporter

logger = logging.getLogger(__name__)

_reporters: dict[str, ChatProgressReporter] = {}
_bus: MessageBus | None = None


def install_bus(bus: MessageBus) -> None:
    """Gateway installs the MessageBus reference so clawbot tools can
    launch progress reporters. Called once from Gateway.__init__."""
    global _bus
    _bus = bus


def get_bus() -> MessageBus | None:
    return _bus


def register_reporter(run_id: str, reporter: ChatProgressReporter) -> None:
    existing = _reporters.get(run_id)
    if existing is not None:
        logger.warning("reporter registry: overwriting existing reporter for run %s", run_id)
        try:
            existing.stop()
        except Exception:
            logger.exception("failed to stop existing reporter for run %s", run_id)
    _reporters[run_id] = reporter


def unregister_reporter(run_id: str) -> None:
    _reporters.pop(run_id, None)


def get_reporter(run_id: str) -> ChatProgressReporter | None:
    return _reporters.get(run_id)


def all_reporters() -> list[ChatProgressReporter]:
    return list(_reporters.values())


def clear_registry_for_shutdown() -> None:
    """Cancel every live reporter. Called on Gateway shutdown."""
    for run_id, reporter in list(_reporters.items()):
        try:
            reporter.stop()
        except Exception:
            logger.exception("failed to stop reporter for run %s on shutdown", run_id)
    _reporters.clear()
