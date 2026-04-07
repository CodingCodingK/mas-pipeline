"""Verification for user system: get_current_user, caching, error handling."""

import asyncio
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth.user import get_current_user
from src.models import User
from src.project.config import get_settings


async def test_get_current_user():
    """Test that get_current_user returns a valid User from the database."""
    print("=== get_current_user: returns valid User ===")

    # Reset cache for clean test
    import src.auth.user as user_mod

    user_mod._cached_user = None

    user = await get_current_user()

    assert isinstance(user, User), f"Expected User instance, got {type(user)}"
    assert user.id > 0, f"Expected positive id, got {user.id}"

    settings = get_settings()
    assert user.name == settings.default_user.name, (
        f"Expected name '{settings.default_user.name}', got '{user.name}'"
    )
    assert user.email is not None, "Expected email to be set"
    assert isinstance(user.config, dict), f"Expected dict config, got {type(user.config)}"
    assert user.created_at is not None, "Expected created_at to be set"

    print(f"  User: id={user.id}, name={user.name}, email={user.email}")
    print(f"  config: {user.config}")
    print(f"  created_at: {user.created_at}")
    print("  OK")
    return user


async def test_caching():
    """Test that get_current_user caches the result."""
    print("=== get_current_user: caching ===")

    user1 = await get_current_user()
    user2 = await get_current_user()

    assert user1 is user2, "Expected same instance (cached), got different objects"
    print("  user1 is user2: True (cached)")
    print("  OK")


async def test_user_not_found():
    """Test that a missing user raises ValueError."""
    print("=== get_current_user: user not found ===")

    import src.auth.user as user_mod

    user_mod._cached_user = None

    # Temporarily override settings to use a non-existent user name
    from src.project.config import get_settings

    settings = get_settings()
    original_name = settings.default_user.name
    settings.default_user.name = "nonexistent_user_xyz"

    try:
        await get_current_user()
        print("  FAIL: expected ValueError")
    except ValueError as e:
        assert "not found" in str(e), f"Expected 'not found' in error, got: {e}"
        print(f"  ValueError raised: {e}")
        print("  OK")
    finally:
        settings.default_user.name = original_name
        user_mod._cached_user = None


def test_user_orm_columns():
    """Test that User ORM model has the expected columns."""
    print("=== User ORM columns ===")

    columns = {c.key for c in User.__table__.columns}
    expected = {"id", "name", "email", "config", "created_at"}
    assert columns == expected, f"Expected columns {expected}, got {columns}"
    print(f"  columns: {columns}")
    print("  OK")


async def main():
    print("\n--- User System Verification ---\n")

    # Import db init to ensure connections are ready
    from src.db import close_db, init_db

    await init_db()

    try:
        test_user_orm_columns()
        await test_get_current_user()
        await test_caching()
        await test_user_not_found()
    finally:
        await close_db()

    print("\n[PASS] All user system tests passed!\n")


if __name__ == "__main__":
    # Windows: psycopg requires SelectorEventLoop (ProactorEventLoop incompatible)
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
