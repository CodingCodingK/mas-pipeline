"""Per-user notification channel preferences CRUD (user_notify_preferences)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


async def get(
    user_id: int, event_type: str, session_factory
) -> list[str]:
    """Return the channel list for (user_id, event_type) or `[]` on miss."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT channels FROM user_notify_preferences "
                "WHERE user_id = :uid AND event_type = :et"
            ),
            {"uid": user_id, "et": event_type},
        )
        row = result.first()
    if row is None:
        return []
    channels = row[0]
    if isinstance(channels, str):
        try:
            channels = json.loads(channels)
        except json.JSONDecodeError:
            return []
    if not isinstance(channels, list):
        return []
    return [str(c) for c in channels]


async def get_all(user_id: int, session_factory) -> dict[str, list[str]]:
    """Return full `{event_type: channels}` map for a user."""
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT event_type, channels FROM user_notify_preferences "
                "WHERE user_id = :uid"
            ),
            {"uid": user_id},
        )
        rows = result.all()
    out: dict[str, list[str]] = {}
    for event_type, channels in rows:
        if isinstance(channels, str):
            try:
                channels = json.loads(channels)
            except json.JSONDecodeError:
                channels = []
        if not isinstance(channels, list):
            channels = []
        out[str(event_type)] = [str(c) for c in channels]
    return out


async def set(
    user_id: int, event_type: str, channels: list[str], session_factory
) -> None:
    """Upsert a preference row."""
    payload: Any = json.dumps(list(channels))
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO user_notify_preferences "
                "(user_id, event_type, channels, updated_at) "
                "VALUES (:uid, :et, CAST(:ch AS JSONB), NOW()) "
                "ON CONFLICT (user_id, event_type) DO UPDATE "
                "SET channels = EXCLUDED.channels, updated_at = NOW()"
            ),
            {"uid": user_id, "et": event_type, "ch": payload},
        )
        await session.commit()
