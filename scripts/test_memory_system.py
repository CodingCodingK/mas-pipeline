"""Memory system tests: store CRUD, selector, tools, context builder integration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.base import ToolContext, ToolResult

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


# ── 1. Memory store — type validation ───────────────────────

print("\n=== 1. Memory store type validation ===")

from src.memory.store import VALID_TYPES

check("Valid types defined", len(VALID_TYPES) == 4)
check("fact in types", "fact" in VALID_TYPES)
check("preference in types", "preference" in VALID_TYPES)
check("context in types", "context" in VALID_TYPES)
check("instruction in types", "instruction" in VALID_TYPES)


async def test_write_invalid_type():
    with patch("src.memory.store.get_db"):
        from src.memory.store import write_memory

        try:
            await write_memory(1, "bogus", "name", "desc", "content")
            check("Invalid type raises", False, "no exception")
        except ValueError as e:
            check("Invalid type raises", True)
            check("Error mentions type", "bogus" in str(e))


asyncio.run(test_write_invalid_type())


# ── 2. Memory store — CRUD with mocked DB ───────────────────

print("\n=== 2. Memory store CRUD ===")


class FakeMemory:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


async def test_write_memory():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.memory.store.get_db", return_value=mock_session):
        from src.memory.store import write_memory

        mem = await write_memory(1, "fact", "Test", "A test", "content")
    check("Write calls add", mock_session.add.called)
    check("Write calls commit", mock_session.commit.called)


asyncio.run(test_write_memory())


async def test_get_not_found():
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.memory.store.get_db", return_value=mock_session):
        from src.memory.store import MemoryNotFoundError, get_memory

        try:
            await get_memory(999)
            check("Not found raises", False)
        except MemoryNotFoundError:
            check("Not found raises", True)


asyncio.run(test_get_not_found())


async def test_delete_memory():
    fake_mem = FakeMemory(id=1, name="test")
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=fake_mem)
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("src.memory.store.get_db", return_value=mock_session):
        from src.memory.store import delete_memory

        await delete_memory(1)
    check("Delete calls delete", mock_session.delete.called)
    check("Delete calls commit", mock_session.commit.called)


asyncio.run(test_delete_memory())


# ── 3. Memory selector — mocked LLM ─────────────────────────

print("\n=== 3. Memory selector ===")


async def test_select_empty():
    with patch("src.memory.selector.list_memories", AsyncMock(return_value=[])):
        from src.memory.selector import select_relevant

        result = await select_relevant(1, "anything")
    check("Empty project returns []", result == [])


asyncio.run(test_select_empty())


async def test_select_relevant():
    fake_memories = [
        FakeMemory(id=1, type="fact", name="Dark mode", description="User prefers dark mode"),
        FakeMemory(id=2, type="fact", name="Deadline", description="May 1st deadline"),
        FakeMemory(id=3, type="preference", name="Language", description="Prefers Python"),
    ]

    mock_response = MagicMock()
    mock_response.content = "[1, 3]"

    mock_adapter = AsyncMock()
    mock_adapter.call = AsyncMock(return_value=mock_response)

    with (
        patch("src.memory.selector.list_memories", AsyncMock(return_value=fake_memories)),
        patch("src.memory.selector.route", return_value=mock_adapter),
        patch("src.memory.selector.get_memory", AsyncMock(side_effect=lambda mid: next(m for m in fake_memories if m.id == mid))),
    ):
        from src.memory.selector import select_relevant

        result = await select_relevant(1, "What does user prefer?", limit=5)

    check("Selector returns 2", len(result) == 2)
    check("First is id=1", result[0].id == 1)
    check("Second is id=3", result[1].id == 3)
    check("LLM called", mock_adapter.call.called)


asyncio.run(test_select_relevant())


# ── 4. Memory tools ──────────────────────────────────────────

print("\n=== 4. Memory tools ===")

from src.tools.builtins.memory import MemoryReadTool, MemoryWriteTool

read_tool = MemoryReadTool()
write_tool = MemoryWriteTool()

check("Read tool name", read_tool.name == "memory_read")
check("Write tool name", write_tool.name == "memory_write")
check("Read is concurrency safe", read_tool.is_concurrency_safe({}))
check("Read is read only", read_tool.is_read_only({}))
check("Write is not concurrency safe", not write_tool.is_concurrency_safe({}))
check("Write is not read only", not write_tool.is_read_only({}))

ctx = ToolContext(agent_id="test", run_id="r1", project_id=1)


async def test_read_list_empty():
    with patch("src.memory.store.list_memories", AsyncMock(return_value=[])):
        result = await read_tool.call({"action": "list"}, ctx)
    check("List empty returns success", result.success)
    check("List empty message", "No memories" in result.output)


asyncio.run(test_read_list_empty())


async def test_read_list():
    fake_mems = [
        FakeMemory(id=1, type="fact", name="Pref", description="desc1"),
        FakeMemory(id=2, type="context", name="Ctx", description="desc2"),
    ]
    with patch("src.memory.store.list_memories", AsyncMock(return_value=fake_mems)):
        result = await read_tool.call({"action": "list"}, ctx)
    check("List returns items", "[1]" in result.output and "[2]" in result.output)


asyncio.run(test_read_list())


async def test_read_get():
    fake_mem = FakeMemory(id=1, type="fact", name="Pref", description="desc", content="full content here")
    with patch("src.memory.store.get_memory", AsyncMock(return_value=fake_mem)):
        result = await read_tool.call({"action": "get", "memory_id": 1}, ctx)
    check("Get returns content", "full content here" in result.output)


asyncio.run(test_read_get())


async def test_write_tool_invalid_type():
    from src.memory.store import VALID_TYPES as VT

    with patch("src.memory.store.write_memory", AsyncMock(side_effect=ValueError("Invalid memory type 'bogus'"))):
        result = await write_tool.call(
            {"action": "write", "type": "bogus", "name": "x", "description": "y", "content": "z"},
            ctx,
        )
    check("Write invalid type fails", not result.success)
    check("Write error message", "bogus" in result.output)


asyncio.run(test_write_tool_invalid_type())


async def test_write_tool_success():
    fake_mem = FakeMemory(id=42, name="Test mem")
    with patch("src.memory.store.write_memory", AsyncMock(return_value=fake_mem)):
        result = await write_tool.call(
            {"action": "write", "type": "fact", "name": "Test mem", "description": "d", "content": "c"},
            ctx,
        )
    check("Write success", result.success)
    check("Write output has id", "42" in result.output)


asyncio.run(test_write_tool_success())


# ── 5. Context builder memory layer ─────────────────────────

print("\n=== 5. Context builder memory layer ===")

from src.agent.context import build_system_prompt

prompt_no_mem = build_system_prompt("You are a helper.")
check("No memory: no Memory section", "# Memory" not in prompt_no_mem)

prompt_with_mem = build_system_prompt("You are a helper.", memory_context="User prefers dark mode.")
check("With memory: has Memory section", "# Memory" in prompt_with_mem)
check("With memory: content present", "dark mode" in prompt_with_mem)


# ── 6. Global tool pool ─────────────────────────────────────

print("\n=== 6. Global tool pool ===")

from src.tools.builtins import get_all_tools

all_tools = get_all_tools()
check("memory_read in pool", "memory_read" in all_tools)
check("memory_write in pool", "memory_write" in all_tools)
check("Total tools = 6", len(all_tools) == 6, f"got {len(all_tools)}: {list(all_tools.keys())}")


# ── Summary ──────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
