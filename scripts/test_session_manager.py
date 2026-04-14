"""Session manager tests: Conversation CRUD, orphan cleanup."""

from __future__ import annotations

import asyncio
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


# ── Summary ──────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
