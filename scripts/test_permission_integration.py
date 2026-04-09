"""Integration tests for permission in factory and pipeline."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

from src.permissions.types import PermissionMode, PermissionRule

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")


async def run_tests() -> None:
    # ── create_agent with permission_mode ──────────────────

    print("=== create_agent permission_mode ===")

    # Mock get_settings to avoid file dependency
    mock_settings = type("S", (), {
        "hooks": {},
        "permissions": {"deny": ["shell(rm *)"]},
    })()

    with patch("src.agent.factory.get_settings", return_value=mock_settings):
        from src.agent.factory import create_agent

        state = await create_agent(
            role="researcher",
            task_description="test task",
            permission_mode=PermissionMode.NORMAL,
        )

        check("state created", state is not None)
        check("tool_context has permission_checker", state.tool_context.permission_checker is not None)

        checker = state.tool_context.permission_checker
        check("checker mode is NORMAL", checker._mode == PermissionMode.NORMAL)

        # Verify deny rule loaded
        deny_rules = checker.get_deny_rules()
        check("deny rule loaded", len(deny_rules) == 1)
        check("deny rule is shell(rm *)", deny_rules[0].tool_name == "shell" and deny_rules[0].pattern == "rm *")

    # ── create_agent with bypass — no permission hooks ────

    print("\n=== create_agent BYPASS mode ===")

    with patch("src.agent.factory.get_settings", return_value=mock_settings):
        state_bypass = await create_agent(
            role="researcher",
            task_description="test task",
            permission_mode=PermissionMode.BYPASS,
        )
        check("bypass: checker exists", state_bypass.tool_context.permission_checker is not None)
        check("bypass: mode is BYPASS", state_bypass.tool_context.permission_checker._mode == PermissionMode.BYPASS)
        # In bypass mode, rules are empty (skip loading)
        check("bypass: no rules", len(state_bypass.tool_context.permission_checker._all_rules) == 0)

    # ── create_agent with parent_deny_rules ───────────────

    print("\n=== create_agent parent_deny_rules ===")

    parent_deny = [PermissionRule("write", "/etc/*", "deny")]
    with patch("src.agent.factory.get_settings", return_value=mock_settings):
        state_child = await create_agent(
            role="researcher",
            task_description="child task",
            permission_mode=PermissionMode.NORMAL,
            parent_deny_rules=parent_deny,
        )
        child_deny = state_child.tool_context.permission_checker.get_deny_rules()
        check("child has parent deny + own deny", len(child_deny) == 2)
        tool_names = [r.tool_name for r in child_deny]
        check("write deny from parent", "write" in tool_names)
        check("shell deny from settings", "shell" in tool_names)

    # ── execute_pipeline permission_mode passthrough ──────

    print("\n=== execute_pipeline permission_mode ===")

    # We can't easily test execute_pipeline without DB, but we can verify
    # the parameter exists and defaults work
    from src.engine.pipeline import execute_pipeline
    import inspect

    sig = inspect.signature(execute_pipeline)
    check("permission_mode param exists", "permission_mode" in sig.parameters)
    check("permission_mode has default", sig.parameters["permission_mode"].default is None)

    # ── SpawnAgentTool deny inheritance ───────────────────

    print("\n=== SpawnAgentTool deny inheritance ===")

    from src.tools.builtins.spawn_agent import SpawnAgentTool
    from src.tools.base import ToolContext
    from src.permissions.checker import PermissionChecker

    # Create a parent context with permission checker
    parent_checker = PermissionChecker(
        [PermissionRule("shell", "rm *", "deny")],
        PermissionMode.STRICT,
    )
    parent_ctx = ToolContext(
        agent_id="test:parent",
        run_id="run-123",
        permission_checker=parent_checker,
    )

    # Verify the deny rules can be extracted
    extracted = parent_ctx.permission_checker.get_deny_rules()
    check("parent deny extractable", len(extracted) == 1)
    check("parent deny rule correct", extracted[0].tool_name == "shell")

    # Verify permission mode extraction
    check("parent mode extractable", parent_ctx.permission_checker._mode == PermissionMode.STRICT)


asyncio.run(run_tests())

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
