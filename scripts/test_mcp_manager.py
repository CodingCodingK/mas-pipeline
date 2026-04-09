"""Unit tests for src/mcp/manager.py — MCPManager."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp.manager import MCPManager

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


def mock_client_factory(tools_by_server):
    """Patch MCPClient to return predefined tools per server."""
    created = {}

    class FakeMCPClient:
        def __init__(self, transport):
            self._transport = transport
            self._name = None

        async def initialize(self):
            return {"protocolVersion": "2024-11-05", "capabilities": {}}

        async def list_tools(self):
            # We need to figure out the server name from context
            return self._tools

        async def shutdown(self):
            pass

    return FakeMCPClient


# --- start: concurrent, stdio/HTTP detection ---

print("=== MCPManager: start ===")


async def test_start():
    mgr = MCPManager()

    from src.mcp.tool import MCPTool

    mock_client_inst = AsyncMock()
    mock_client_inst.initialize = AsyncMock(return_value={"protocolVersion": "2024-11-05"})

    async def fake_create_tools(name, client):
        return [MCPTool(name, f"tool_{i}", f"desc {i}", {}, client) for i in range(2)]

    with patch("src.mcp.manager._create_transport", return_value=MagicMock()), \
         patch("src.mcp.manager.MCPClient", return_value=mock_client_inst), \
         patch("src.mcp.manager.create_mcp_tools", side_effect=fake_create_tools):

        await mgr.start({
            "github": {"command": "npx", "args": ["-y", "server-github"]},
            "postgres": {"url": "http://localhost:3001/mcp"},
        })

        check("two servers connected", len(mgr._clients) == 2)
        check("github connected", "github" in mgr._clients)
        check("postgres connected", "postgres" in mgr._clients)
        check("github has tools", len(mgr._tools["github"]) == 2)
        check("postgres has tools", len(mgr._tools["postgres"]) == 2)


asyncio.run(test_start())

# --- start: failure isolation ---

print("\n=== MCPManager: failure isolation ===")


async def test_failure_isolation():
    mgr = MCPManager()

    from src.mcp.tool import MCPTool

    call_count = [0]

    async def mock_init():
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("server down")
        return {"protocolVersion": "2024-11-05"}

    mock_client_inst = AsyncMock()
    mock_client_inst.initialize = AsyncMock(side_effect=mock_init)

    async def fake_create_tools(name, client):
        return [MCPTool(name, "tool1", "d", {}, client)]

    with patch("src.mcp.manager._create_transport", return_value=MagicMock()), \
         patch("src.mcp.manager.MCPClient", return_value=mock_client_inst), \
         patch("src.mcp.manager.create_mcp_tools", side_effect=fake_create_tools):

        await mgr.start({
            "github": {"command": "npx", "args": []},
            "postgres": {"url": "http://localhost:3001"},
        })

        # One failed, one succeeded
        check("only one server connected", len(mgr._clients) == 1)
        check("one server survived", len(mgr._clients) == 1)


asyncio.run(test_failure_isolation())

# --- get_tools ---

print("\n=== MCPManager: get_tools ===")


async def test_get_tools():
    mgr = MCPManager()

    from src.mcp.tool import MCPTool
    mock_client = MagicMock()
    mgr._tools = {
        "github": [
            MCPTool("github", "create_issue", "d", {}, mock_client),
            MCPTool("github", "list_prs", "d", {}, mock_client),
        ],
        "postgres": [
            MCPTool("postgres", "query", "d", {}, mock_client),
        ],
    }

    all_tools = mgr.get_tools()
    check("get all returns 3", len(all_tools) == 3)

    gh_tools = mgr.get_tools(["github"])
    check("filter github returns 2", len(gh_tools) == 2)

    pg_tools = mgr.get_tools(["postgres"])
    check("filter postgres returns 1", len(pg_tools) == 1)

    none_tools = mgr.get_tools(["nonexistent"])
    check("unknown server returns empty", len(none_tools) == 0)

    mixed = mgr.get_tools(["github", "nonexistent"])
    check("mixed filter returns 2", len(mixed) == 2)


asyncio.run(test_get_tools())

# --- shutdown ---

print("\n=== MCPManager: shutdown ===")


async def test_shutdown():
    mgr = MCPManager()
    client1 = MagicMock()
    client1.shutdown = AsyncMock()
    client2 = MagicMock()
    client2.shutdown = AsyncMock(side_effect=RuntimeError("shutdown error"))

    mgr._clients = {"server1": client1, "server2": client2}
    mgr._tools = {"server1": [], "server2": []}

    await mgr.shutdown()
    check("client1 shutdown called", client1.shutdown.called)
    check("client2 shutdown called", client2.shutdown.called)
    check("clients cleared", len(mgr._clients) == 0)
    check("tools cleared", len(mgr._tools) == 0)


asyncio.run(test_shutdown())

# --- context manager ---

print("\n=== MCPManager: context manager ===")


async def test_context_manager():
    shutdown_called = False

    class TestMgr(MCPManager):
        async def shutdown(self):
            nonlocal shutdown_called
            shutdown_called = True

    async with TestMgr() as mgr:
        check("returns self", isinstance(mgr, TestMgr))

    check("shutdown called on exit", shutdown_called)


asyncio.run(test_context_manager())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
