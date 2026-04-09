"""Unit tests for src/mcp/tool.py — MCPTool, create_mcp_tools."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp.tool import MCPTool, create_mcp_tools
from src.tools.base import ToolContext, ToolResult

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


def make_context():
    return ToolContext(
        agent_id="test", run_id="run1", project_id=1,
        abort_signal=None, hook_runner=MagicMock(), permission_checker=None,
    )


# --- MCPTool name format ---

print("=== MCPTool: name format ===")

mock_client = MagicMock()
tool = MCPTool(
    server_name="github",
    tool_name="create_issue",
    description="Create a GitHub issue",
    input_schema={"type": "object", "properties": {"title": {"type": "string"}}},
    client=mock_client,
)
check("three-part name", tool.name == "mcp__github__create_issue")
check("description preserved", tool.description == "Create a GitHub issue")
check("input_schema preserved", "title" in tool.input_schema["properties"])
check("not concurrency safe", tool.is_concurrency_safe({}) is False)

# --- MCPTool.call success ---

print("\n=== MCPTool: call success ===")


async def test_call_success():
    client = MagicMock()
    client.call_tool = AsyncMock(return_value="Issue #42 created")
    tool = MCPTool("github", "create_issue", "desc", {}, client)
    ctx = make_context()
    result = await tool.call({"title": "Bug"}, ctx)
    check("success True", result.success is True)
    check("output correct", result.output == "Issue #42 created")
    client.call_tool.assert_called_once_with("create_issue", {"title": "Bug"})


asyncio.run(test_call_success())

# --- MCPTool.call error ---

print("\n=== MCPTool: call error ===")


async def test_call_error():
    client = MagicMock()
    client.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
    tool = MCPTool("github", "create_issue", "desc", {}, client)
    ctx = make_context()
    result = await tool.call({"title": "Bug"}, ctx)
    check("success False", result.success is False)
    check("error in output", "connection lost" in result.output)


asyncio.run(test_call_error())

# --- create_mcp_tools ---

print("\n=== create_mcp_tools ===")


async def test_create_tools():
    client = MagicMock()
    client.list_tools = AsyncMock(return_value=[
        {"name": "create_issue", "description": "Create issue", "inputSchema": {"type": "object"}},
        {"name": "list_prs", "description": "List PRs", "inputSchema": {"type": "object"}},
        {"name": "merge_pr", "description": "Merge PR"},
    ])
    tools = await create_mcp_tools("github", client)
    check("3 tools created", len(tools) == 3)
    check("first name", tools[0].name == "mcp__github__create_issue")
    check("second name", tools[1].name == "mcp__github__list_prs")
    check("third name", tools[2].name == "mcp__github__merge_pr")
    check("all are MCPTool", all(isinstance(t, MCPTool) for t in tools))


asyncio.run(test_create_tools())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
