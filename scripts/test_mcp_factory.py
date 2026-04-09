"""Unit tests for factory MCP integration — create_agent with mcp_manager."""

import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


# Helper: create a fake MCPManager with predefined tools
def make_mcp_manager(tools_by_server):
    from src.mcp.tool import MCPTool
    mgr = MagicMock()
    all_tools = {}
    for srv, tool_names in tools_by_server.items():
        all_tools[srv] = [
            MCPTool(srv, name, f"desc for {name}", {"type": "object"}, MagicMock())
            for name in tool_names
        ]

    def get_tools(server_names=None):
        if server_names is None:
            return [t for tools in all_tools.values() for t in tools]
        result = []
        for name in server_names:
            result.extend(all_tools.get(name, []))
        return result

    mgr.get_tools = MagicMock(side_effect=get_tools)
    return mgr


# --- create_agent with MCP tools (default access all) ---

print("=== Factory: MCP default access all ===")


async def test_mcp_all():
    from src.permissions.types import PermissionMode

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "---\n"
        "\n"
        "You are a test agent.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        role_path = Path(tmp) / "agents" / "tester.md"
        role_path.parent.mkdir()
        role_path.write_text(role_content, encoding="utf-8")

        mcp_mgr = make_mcp_manager({"github": ["create_issue", "list_prs"], "postgres": ["query"]})

        # Mock settings with mcp_default_access=all
        mock_settings = MagicMock()
        mock_settings.permissions = {}
        mock_settings.hooks = {}
        mock_settings.mcp_default_access = "all"

        with patch("src.agent.factory._AGENTS_DIR", role_path.parent), \
             patch("src.agent.factory.route", return_value=MagicMock()), \
             patch("src.agent.factory.get_settings", return_value=mock_settings):
            from src.agent.factory import create_agent
            state = await create_agent(
                role="tester",
                task_description="test",
                permission_mode=PermissionMode.BYPASS,
                mcp_manager=mcp_mgr,
            )
            tool_names = list(state.tools._tools.keys())
            check("read_file registered", "read_file" in tool_names)
            check("mcp github tools registered", "mcp__github__create_issue" in tool_names)
            check("mcp postgres tools registered", "mcp__postgres__query" in tool_names)
            check("total tools: 1 builtin + 3 mcp", len(tool_names) == 4)


asyncio.run(test_mcp_all())

# --- create_agent with MCP whitelist ---

print("\n=== Factory: MCP role whitelist ===")


async def test_mcp_whitelist():
    from src.permissions.types import PermissionMode

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "mcp_servers: [github]\n"
        "---\n"
        "\n"
        "You are a test agent.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        role_path = Path(tmp) / "agents" / "tester2.md"
        role_path.parent.mkdir()
        role_path.write_text(role_content, encoding="utf-8")

        mcp_mgr = make_mcp_manager({"github": ["create_issue"], "postgres": ["query"]})

        mock_settings = MagicMock()
        mock_settings.permissions = {}
        mock_settings.hooks = {}
        mock_settings.mcp_default_access = "all"

        with patch("src.agent.factory._AGENTS_DIR", role_path.parent), \
             patch("src.agent.factory.route", return_value=MagicMock()), \
             patch("src.agent.factory.get_settings", return_value=mock_settings):
            from src.agent.factory import create_agent
            state = await create_agent(
                role="tester2",
                task_description="test",
                permission_mode=PermissionMode.BYPASS,
                mcp_manager=mcp_mgr,
            )
            tool_names = list(state.tools._tools.keys())
            check("github tool registered", "mcp__github__create_issue" in tool_names)
            check("postgres tool NOT registered", "mcp__postgres__query" not in tool_names)


asyncio.run(test_mcp_whitelist())

# --- create_agent with MCP default access none ---

print("\n=== Factory: MCP default access none ===")


async def test_mcp_none():
    from src.permissions.types import PermissionMode

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "---\n"
        "\n"
        "You are a test agent.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        role_path = Path(tmp) / "agents" / "tester3.md"
        role_path.parent.mkdir()
        role_path.write_text(role_content, encoding="utf-8")

        mcp_mgr = make_mcp_manager({"github": ["create_issue"]})

        mock_settings = MagicMock()
        mock_settings.permissions = {}
        mock_settings.hooks = {}
        mock_settings.mcp_default_access = "none"

        with patch("src.agent.factory._AGENTS_DIR", role_path.parent), \
             patch("src.agent.factory.route", return_value=MagicMock()), \
             patch("src.agent.factory.get_settings", return_value=mock_settings):
            from src.agent.factory import create_agent
            state = await create_agent(
                role="tester3",
                task_description="test",
                permission_mode=PermissionMode.BYPASS,
                mcp_manager=mcp_mgr,
            )
            tool_names = list(state.tools._tools.keys())
            check("no mcp tools", not any(n.startswith("mcp__") for n in tool_names))
            check("only read_file", tool_names == ["read_file"])


asyncio.run(test_mcp_none())

# --- create_agent without mcp_manager ---

print("\n=== Factory: no mcp_manager ===")


async def test_no_mcp():
    from src.permissions.types import PermissionMode

    role_content = (
        "---\n"
        "model_tier: medium\n"
        "tools: [read_file]\n"
        "---\n"
        "\n"
        "You are a test agent.\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        role_path = Path(tmp) / "agents" / "tester4.md"
        role_path.parent.mkdir()
        role_path.write_text(role_content, encoding="utf-8")

        with patch("src.agent.factory._AGENTS_DIR", role_path.parent), \
             patch("src.agent.factory.route", return_value=MagicMock()):
            from src.agent.factory import create_agent
            state = await create_agent(
                role="tester4",
                task_description="test",
                permission_mode=PermissionMode.BYPASS,
            )
            tool_names = list(state.tools._tools.keys())
            check("no mcp tools", not any(n.startswith("mcp__") for n in tool_names))


asyncio.run(test_no_mcp())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
