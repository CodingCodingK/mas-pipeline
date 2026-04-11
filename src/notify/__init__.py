"""Notify layer: EventBus consumer → rules → multi-channel dispatch."""

from src.notify.events import Notification
from src.notify.notifier import (
    NullNotifier,
    Notifier,
    get_notifier,
    make_project_user_resolver,
    set_notifier,
)

__all__ = [
    "Notification",
    "Notifier",
    "NullNotifier",
    "get_notifier",
    "set_notifier",
    "make_project_user_resolver",
]
