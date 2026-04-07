"""User identity: single-user mode with database-backed lookup."""

from __future__ import annotations

from sqlalchemy import select

from src.db import get_db
from src.models import User
from src.project.config import get_settings

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
        result = await session.execute(select(User).where(User.name == user_name))
        user = result.scalars().first()

    if user is None:
        raise ValueError(
            f"Default user '{user_name}' not found in database. "
            "Run scripts/init_db.sql to seed the default user."
        )

    _cached_user = user
    return _cached_user
