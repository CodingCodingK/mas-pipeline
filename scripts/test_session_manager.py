"""Session manager tests: Conversation CRUD, Agent Session Redis ops, archival, orphan cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.session.manager import (
    ConversationNotFoundError,
    clean_orphan_messages,
)

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


# ── 1. clean_orphan_messages (pure function, no DB/Redis) ──

print("\n=== 1. Orphan cleanup ===")

# All clean
clean_msgs = [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_1", "function": {"name": "read_file", "arguments": {}}}]},
    {"role": "tool", "tool_call_id": "tc_1", "content": "file contents"},
    {"role": "assistant", "content": "done"},
]
result = clean_orphan_messages(clean_msgs)
check("Clean messages unchanged", len(result) == 4)

# Orphan tool result
orphan_msgs = [
    {"role": "user", "content": "hello"},
    {"role": "tool", "tool_call_id": "tc_orphan", "content": "orphan result"},
    {"role": "assistant", "content": "done"},
]
result = clean_orphan_messages(orphan_msgs)
check("Orphan removed", len(result) == 2)
check("Orphan gone", all(m.get("tool_call_id") != "tc_orphan" for m in result))

# Multiple tool calls, one orphan
mixed_msgs = [
    {"role": "assistant", "content": None, "tool_calls": [{"id": "tc_a"}, {"id": "tc_b"}]},
    {"role": "tool", "tool_call_id": "tc_a", "content": "ok"},
    {"role": "tool", "tool_call_id": "tc_b", "content": "ok"},
    {"role": "tool", "tool_call_id": "tc_c", "content": "orphan"},  # no matching tc_c
]
result = clean_orphan_messages(mixed_msgs)
check("Mixed: valid kept", sum(1 for m in result if m.get("role") == "tool") == 2)
check("Mixed: orphan removed", all(m.get("tool_call_id") != "tc_c" for m in result))

# Empty messages
check("Empty messages", clean_orphan_messages([]) == [])

# No tool messages
no_tool = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "bye"}]
check("No tool messages unchanged", clean_orphan_messages(no_tool) == no_tool)


# ── 2. Conversation CRUD (mocked DB) ────────────────────────

print("\n=== 2. Conversation CRUD ===")


class FakeConversation:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 1)
        self.project_id = kwargs.get("project_id", 1)
        self.messages = kwargs.get("messages", [])
        self.created_at = None
        self.updated_at = None


async def test_create_conversation():
    fake_conv = FakeConversation(id=42, project_id=1)

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda c: setattr(c, "id", 42))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.session.manager.get_db", return_value=mock_session):
        from src.session.manager import create_conversation

        conv = await create_conversation(project_id=1)
    check("Create conversation calls add", mock_session.add.called)
    check("Create conversation calls commit", mock_session.commit.called)


asyncio.run(test_create_conversation())


async def test_get_conversation_not_found():
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.session.manager.get_db", return_value=mock_session):
        from src.session.manager import get_conversation

        try:
            await get_conversation(999)
            check("Not found raises error", False, "no exception raised")
        except ConversationNotFoundError:
            check("Not found raises error", True)


asyncio.run(test_get_conversation_not_found())


async def test_append_message():
    fake_conv = FakeConversation(id=1, messages=[{"role": "user", "content": "hi"}])

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=fake_conv)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.session.manager.get_db", return_value=mock_session):
        from src.session.manager import append_message

        await append_message(1, {"role": "assistant", "content": "hello"})

    check("Append adds message", len(fake_conv.messages) == 2)
    check("Append correct content", fake_conv.messages[1]["content"] == "hello")


asyncio.run(test_append_message())


# ── 3. Agent Session Redis ops (mocked Redis) ──────────────

print("\n=== 3. Agent Session Redis ===")


async def test_agent_session_ops():
    mock_redis = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.rpush = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[
        json.dumps({"role": "user", "content": "task"}),
        json.dumps({"role": "assistant", "content": "done"}),
    ])

    with (
        patch("src.session.manager.get_redis", AsyncMock(return_value=mock_redis)),
        patch("src.session.manager.get_settings") as mock_settings,
    ):
        mock_settings.return_value.session.agent_ttl_hours = 24

        from src.session.manager import (
            create_agent_session,
            append_agent_message,
            get_agent_messages,
        )

        # Create
        key = await create_agent_session("agent-1", "run-1")
        check("Session key format", key == "agent_session:agent-1")
        check("TTL set on create", mock_redis.expire.called)
        ttl_arg = mock_redis.expire.call_args[0][1]
        check("TTL is 24h", ttl_arg == 86400)

        # Append
        await append_agent_message(key, {"role": "user", "content": "task"})
        check("RPUSH called", mock_redis.rpush.called)
        check("TTL refreshed on append", mock_redis.expire.call_count >= 2)

        # Get
        messages = await get_agent_messages(key)
        check("Get returns list", isinstance(messages, list))
        check("Get returns 2 messages", len(messages) == 2)
        check("Messages deserialized", messages[0]["role"] == "user")


asyncio.run(test_agent_session_ops())


# ── 4. Agent Session archival (mocked) ──────────────────────

print("\n=== 4. Agent Session archival ===")


async def test_archive():
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[
        json.dumps({"role": "system", "content": "You are..."}),
        json.dumps({"role": "assistant", "content": "result"}),
    ])
    mock_redis.delete = AsyncMock()

    mock_db_session = AsyncMock()
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()
    mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_db_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.session.manager.get_redis", AsyncMock(return_value=mock_redis)),
        patch("src.session.manager.get_db", return_value=mock_db_session),
    ):
        from src.session.manager import archive_agent_session

        await archive_agent_session("agent_session:agent-1", "researcher")

    check("PG insert called", mock_db_session.add.called)
    record = mock_db_session.add.call_args[0][0]
    check("Record ID from key", record.id == "agent-1")
    check("Record role", record.agent_role == "researcher")
    check("Record has 2 messages", len(record.messages) == 2)
    check("Archived_at set", record.archived_at is not None)
    check("Redis key deleted", mock_redis.delete.called)


asyncio.run(test_archive())


async def test_archive_empty():
    mock_redis = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=[])
    mock_redis.delete = AsyncMock()

    mock_db_session = AsyncMock()
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()
    mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_db_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.session.manager.get_redis", AsyncMock(return_value=mock_redis)),
        patch("src.session.manager.get_db", return_value=mock_db_session),
    ):
        from src.session.manager import archive_agent_session

        await archive_agent_session("agent_session:agent-2", "writer")

    record = mock_db_session.add.call_args[0][0]
    check("Empty archive inserts", mock_db_session.add.called)
    check("Empty archive has 0 messages", len(record.messages) == 0)


asyncio.run(test_archive_empty())


# ── Summary ──────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
