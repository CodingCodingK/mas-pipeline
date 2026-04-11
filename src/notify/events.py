"""Notification envelope delivered to channels."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

NotificationEventType = Literal[
    "run_started",
    "run_completed",
    "run_failed",
    "human_review_needed",
    "agent_progress",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid4().hex


@dataclass
class Notification:
    event_type: NotificationEventType
    user_id: int
    title: str
    body: str
    payload: dict[str, Any]
    notification_id: str = field(default_factory=_new_id)
    created_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "title": self.title,
            "body": self.body,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }
