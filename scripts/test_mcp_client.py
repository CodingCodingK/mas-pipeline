"""Unit tests for src/mcp/client.py — MCPClient: initialize, list_tools, call_tool, shutdown."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp.client import MCPClient
from src.mcp.jsonrpc import JSONRPCError

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


def make_mock_transport(responses: dict | None = None):
    """Create a mock transport with predefined responses by method."""
    transport = MagicMock()
    transport.start = AsyncMock()
    transport.close = AsyncMock()
    resp_map = responses or {}

    async def mock_send(msg):
        if "id" not in msg:
            return None  # notification
        method = msg.get("method", "")
        result = resp_map.get(method, {})
        return {"jsonrpc": "2.0", "result": result, "id": msg["id"]}

    transport.send = AsyncMock(side_effect=mock_send)
    return transport


# --- initialize ---

print("=== MCPClient: initialize ===")


async def test_initialize():
    transport = make_mock_transport({
        "initialize": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test-server"},
        },
    })
    client = MCPClient(transport)
    result = await client.initialize()

    check("start called", transport.start.called)
    check("result has protocolVersion", result.get("protocolVersion") == "2024-11-05")
    check("server capabilities stored", "tools" in client._server_capabilities)
    # 2 calls: initialize request + initialized notification
    check("two sends (request + notification)", transport.send.call_count == 2)


asyncio.run(test_initialize())

# --- list_tools ---

print("\n=== MCPClient: list_tools ===")


async def test_list_tools():
    transport = make_mock_transport({
        "initialize": {"protocolVersion": "2024-11-05", "capabilities": {}},
        "tools/list": {
            "tools": [
                {"name": "create_issue", "description": "Create issue", "inputSchema": {"type": "object"}},
                {"name": "list_prs", "description": "List PRs", "inputSchema": {"type": "object"}},
            ],
        },
    })
    client = MCPClient(transport)
    await client.initialize()
    tools = await client.list_tools()
    check("returns 2 tools", len(tools) == 2)
    check("first tool name", tools[0]["name"] == "create_issue")
    check("second tool name", tools[1]["name"] == "list_prs")


asyncio.run(test_list_tools())

# --- call_tool ---

print("\n=== MCPClient: call_tool success ===")


async def test_call_tool():
    transport = make_mock_transport({
        "initialize": {"protocolVersion": "2024-11-05", "capabilities": {}},
        "tools/call": {
            "content": [{"type": "text", "text": "Issue #42 created"}],
        },
    })
    client = MCPClient(transport)
    await client.initialize()
    result = await client.call_tool("create_issue", {"title": "Bug"})
    check("returns text content", result == "Issue #42 created")


asyncio.run(test_call_tool())

print("\n=== MCPClient: call_tool isError ===")


async def test_call_tool_error():
    transport = MagicMock()
    transport.start = AsyncMock()
    transport.close = AsyncMock()

    call_count = [0]

    async def mock_send(msg):
        if "id" not in msg:
            return None
        method = msg.get("method", "")
        if method == "initialize":
            return {"jsonrpc": "2.0", "result": {"protocolVersion": "2024-11-05", "capabilities": {}}, "id": msg["id"]}
        if method == "tools/call":
            return {"jsonrpc": "2.0", "result": {
                "content": [{"type": "text", "text": "Permission denied"}],
                "isError": True,
            }, "id": msg["id"]}
        return {"jsonrpc": "2.0", "result": {}, "id": msg["id"]}

    transport.send = AsyncMock(side_effect=mock_send)
    client = MCPClient(transport)
    await client.initialize()

    try:
        await client.call_tool("admin_op", {})
        check("raises on isError", False)
    except JSONRPCError as e:
        check("raises on isError", True)
        check("error contains text", "Permission denied" in str(e))


asyncio.run(test_call_tool_error())

# --- shutdown ---

print("\n=== MCPClient: shutdown ===")


async def test_shutdown():
    transport = make_mock_transport({
        "initialize": {"protocolVersion": "2024-11-05", "capabilities": {}},
        "shutdown": {},
    })
    client = MCPClient(transport)
    await client.initialize()
    await client.shutdown()
    check("transport closed", transport.close.called)


asyncio.run(test_shutdown())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
