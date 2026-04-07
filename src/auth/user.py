"""User identity: single-user mode with database-backed lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    from datetime import datetime

from src.db import get_db
from src.project.config import get_settings

# ── Model ──────────────────────────────────────────────────


@dataclass
class User:
    id: int
    name: str
    email: str | None
    config: dict
    created_at: datetime


# ── Module-level cache ─────────────────────────────────────

_cached_user: User | None = None


async def get_current_user() -> User:
    """Return the default user (single-user mode).

    Reads `default_user.name` from settings, queries the `users` table,
    and caches the result for the process lifetime.
    """
    global _cached_user
    if _cached_user is not None:
        return _cached_user

    settings = get_settings()
    user_name = settings.default_user.name

    async with get_db() as session:
        row = (
            await session.execute(
                sa.text("SELECT id, name, email, config, created_at FROM users WHERE name = :name"),
                {"name": user_name},
            )
        ).mappings().first()

    if row is None:
        raise ValueError(
            f"Default user '{user_name}' not found in database. "
            "Run scripts/init_db.sql to seed the default user."
        )

    _cached_user = User(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        config=row["config"] if isinstance(row["config"], dict) else {},
        created_at=row["created_at"],
    )
    return _cached_user
