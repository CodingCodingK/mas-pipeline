"""Unit tests for permission hook integration — callable executor, register_permission_hooks."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hooks.config import HookConfig
from src.hooks.runner import HookRunner
from src.hooks.types import HookEvent, HookEventType, HookResult
from src.permissions.checker import PermissionChecker
from src.permissions.hooks import register_permission_hooks
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
    # ── Callable executor in HookRunner ────────────────────

    print("=== Callable Executor ===")

    async def allow_hook(event: HookEvent) -> HookResult:
        return HookResult(action="allow")

    async def deny_hook(event: HookEvent) -> HookResult:
        return HookResult(action="deny", reason="test deny")

    async def slow_hook(event: HookEvent) -> HookResult:
        await asyncio.sleep(10)
        return HookResult(action="deny")

    async def error_hook(event: HookEvent) -> HookResult:
        raise RuntimeError("boom")

    # Test allow callable
    runner = HookRunner()
    runner.register(
        HookEventType.PRE_TOOL_USE,
        HookConfig(type="callable", callable_fn=allow_hook, timeout=5),
    )
    event = HookEvent(event_type=HookEventType.PRE_TOOL_USE, payload={"tool_name": "test"})
    result = await runner.run(event)
    check("callable allow", result.action == "allow")

    # Test deny callable
    runner2 = HookRunner()
    runner2.register(
        HookEventType.PRE_TOOL_USE,
        HookConfig(type="callable", callable_fn=deny_hook, timeout=5),
    )
    result = await runner2.run(event)
    check("callable deny", result.action == "deny")
    check("callable deny reason", result.reason == "test deny")

    # Test timeout (short timeout so it triggers fast)
    runner3 = HookRunner()
    runner3.register(
        HookEventType.PRE_TOOL_USE,
        HookConfig(type="callable", callable_fn=slow_hook, timeout=0.1),
    )
    result = await runner3.run(event)
    check("callable timeout → allow", result.action == "allow")

    # Test error → allow (non-blocking)
    runner4 = HookRunner()
    runner4.register(
        HookEventType.PRE_TOOL_USE,
        HookConfig(type="callable", callable_fn=error_hook, timeout=5),
    )
    result = await runner4.run(event)
    check("callable error → allow", result.action == "allow")

    # ── register_permission_hooks ──────────────────────────

    print("\n=== register_permission_hooks ===")

    # Deny rule triggers hook deny
    rules = [PermissionRule("shell", "rm *", "deny")]
    checker = PermissionChecker(rules, PermissionMode.NORMAL)
    runner5 = HookRunner()
    register_permission_hooks(runner5, checker)

    event = HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": "shell", "tool_input": {"command": "rm -rf /"}},
    )
    result = await runner5.run(event)
    check("permission deny via hook", result.action == "deny")
    check("permission deny has reason", len(result.reason) > 0)

    # Allow passes through
    event_allow = HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": "shell", "tool_input": {"command": "ls"}},
    )
    result = await runner5.run(event_allow)
    check("permission allow via hook", result.action == "allow")

    # No match → allow
    event_other = HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": "read_file", "tool_input": {"file_path": "test.txt"}},
    )
    result = await runner5.run(event_other)
    check("permission no match → allow", result.action == "allow")

    # Ask → fallback deny (no responder)
    ask_rules = [PermissionRule("shell", None, "ask")]
    ask_checker = PermissionChecker(ask_rules, PermissionMode.NORMAL)
    runner6 = HookRunner()
    register_permission_hooks(runner6, ask_checker)

    event_ask = HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": "shell", "tool_input": {"command": "ls"}},
    )
    result = await runner6.run(event_ask)
    check("ask fallback → deny", result.action == "deny")
    check("ask reason mentions responder", "responder" in result.reason.lower())

    # Empty rules → no hook registered
    empty_checker = PermissionChecker([], PermissionMode.NORMAL)
    runner7 = HookRunner()
    register_permission_hooks(runner7, empty_checker)
    check("empty rules: no hooks registered", len(runner7._hooks) == 0)

    # ── Permission + other hooks coexist ───────────────────

    print("\n=== Coexistence with other hooks ===")

    runner8 = HookRunner()
    # Register a command-style allow hook (we'll use callable to simulate)
    async def audit_hook(event: HookEvent) -> HookResult:
        return HookResult(action="allow", additional_context="audit: logged")

    runner8.register(
        HookEventType.PRE_TOOL_USE,
        HookConfig(type="callable", callable_fn=audit_hook, timeout=5),
    )
    # Also register permission deny
    deny_checker = PermissionChecker([PermissionRule("shell", "rm *", "deny")], PermissionMode.NORMAL)
    register_permission_hooks(runner8, deny_checker)

    event_rm = HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": "shell", "tool_input": {"command": "rm -rf /"}},
    )
    result = await runner8.run(event_rm)
    check("permission deny wins over audit allow", result.action == "deny")

    # Non-deny case: additional_context from audit preserved
    event_ls = HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": "shell", "tool_input": {"command": "ls"}},
    )
    result = await runner8.run(event_ls)
    check("audit context preserved", "audit" in result.additional_context)


asyncio.run(run_tests())

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
