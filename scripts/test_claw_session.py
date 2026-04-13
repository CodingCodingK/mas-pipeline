"""Unit tests for src/bus/session.py — ChatSession CRUD + Redis cache."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.session import (
    _CACHE_PREFIX,
    get_session_history,
    refresh_session,
    resolve_session,
)
from src.models import ChatSession, Conversation

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


# === resolve_session: Redis cache hit ===

print("=== resolve_session: cache hit ===")


async def test_cache_hit():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps({
        "id": 10,
        "project_id": 1,
        "conversation_id": 20,
    }))

    with patch("src.bus.session.get_redis", return_value=mock_redis):
        session = await resolve_session("discord:ch1", "discord", "ch1", 1)

    check("session_key", session.session_key == "discord:ch1")
    check("id from cache", session.id == 10)
    check("project_id from cache", session.project_id == 1)
    check("conversation_id from cache", session.conversation_id == 20)
    check("channel", session.channel == "discord")
    check("chat_id", session.chat_id == "ch1")
    mock_redis.get.assert_called_once_with(f"{_CACHE_PREFIX}discord:ch1")


asyncio.run(test_cache_hit())


# === resolve_session: cache miss, PG hit ===

print("\n=== resolve_session: PG fallback ===")


async def test_pg_fallback():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # Cache miss
    mock_redis.set = AsyncMock()

    existing = ChatSession(
        id=5, session_key="qq:g1", channel="qq", chat_id="g1",
        project_id=1, conversation_id=15, status="active",
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = existing

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("src.bus.session.get_redis", return_value=mock_redis), \
         patch("src.bus.session.get_db", return_value=mock_db):
        session = await resolve_session("qq:g1", "qq", "g1", 1)

    check("returns PG session", session.id == 5)
    check("conversation_id", session.conversation_id == 15)
    # Should have cached it
    check("redis.set called", mock_redis.set.called)


asyncio.run(test_pg_fallback())


# === resolve_session: cache miss, PG miss → create ===

print("\n=== resolve_session: create new ===")


async def test_create_new():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None  # Not in PG

    new_session = ChatSession(
        id=99, session_key="wechat:wx1", channel="wechat", chat_id="wx1",
        project_id=2, conversation_id=50,
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=lambda s: setattr(s, 'id', 99))
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("src.bus.session.get_redis", return_value=mock_redis), \
         patch("src.bus.session.get_db", return_value=mock_db):
        session = await resolve_session("wechat:wx1", "wechat", "wx1", 2)

    check("session created", session is not None)
    check("session_key set", session.session_key == "wechat:wx1")
    check("channel set", session.channel == "wechat")
    check("project_id set", session.project_id == 2)
    # db.add called twice: once for Conversation, once for ChatSession
    check("db.add called for conv + session", mock_db.add.call_count == 2)
    check("redis cached", mock_redis.set.called)


asyncio.run(test_create_new())


# === refresh_session: updates PG + refreshes Redis TTL ===

print("\n=== refresh_session ===")


async def test_refresh():
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock()

    mock_session = MagicMock()
    mock_session.last_active_at = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_session

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    with patch("src.bus.session.get_redis", return_value=mock_redis), \
         patch("src.bus.session.get_db", return_value=mock_db):
        await refresh_session("discord:ch1", ttl_hours=12)

    check("redis expire called", mock_redis.expire.called)
    expire_args = mock_redis.expire.call_args
    check("expire key correct", expire_args[0][0] == f"{_CACHE_PREFIX}discord:ch1")
    check("expire ttl = 12h in seconds", expire_args[0][1] == 12 * 3600)
    check("last_active_at updated", mock_session.last_active_at is not None)


asyncio.run(test_refresh())


# === get_session_history: loads, cleans, trims ===

print("\n=== get_session_history ===")


async def test_history():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "response"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "response 2"},
        {"role": "user", "content": "third"},
    ]

    with patch("src.bus.session.get_messages", new_callable=AsyncMock, return_value=messages), \
         patch("src.bus.session.clean_orphan_messages", side_effect=lambda m: m):
        history = await get_session_history(conversation_id=1)

    check("full history returned (no cap)", len(history) == 5)
    check("kept latest", history[-1]["content"] == "third")
    check("kept oldest", history[0]["content"] == "first")


asyncio.run(test_history())


# === get_session_history: skips leading tool results ===

print("\n=== get_session_history: skip leading tool ===")


async def test_history_skip_tool():
    messages = [
        {"role": "tool", "content": "orphan tool result"},
        {"role": "tool", "content": "another orphan"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    with patch("src.bus.session.get_messages", new_callable=AsyncMock, return_value=messages), \
         patch("src.bus.session.clean_orphan_messages", side_effect=lambda m: m):
        history = await get_session_history(conversation_id=1)

    check("tool results stripped", len(history) == 2)
    check("starts with user", history[0]["role"] == "user")


asyncio.run(test_history_skip_tool())


# === get_session_history: empty messages ===

print("\n=== get_session_history: empty ===")


async def test_history_empty():
    with patch("src.bus.session.get_messages", new_callable=AsyncMock, return_value=[]), \
         patch("src.bus.session.clean_orphan_messages", side_effect=lambda m: m):
        history = await get_session_history(conversation_id=1)

    check("empty list returned", history == [])


asyncio.run(test_history_empty())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
