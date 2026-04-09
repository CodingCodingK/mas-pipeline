"""Permission ↔ Hook bridge: register permission rules as a PreToolUse hook."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.hooks.config import HookConfig
from src.hooks.types import HookEvent, HookEventType, HookResult

if TYPE_CHECKING:
    from src.hooks.runner import HookRunner
    from src.permissions.checker import PermissionChecker


def register_permission_hooks(
    hook_runner: HookRunner,
    checker: PermissionChecker,
) -> None:
    """Register the permission checker as a callable PreToolUse hook.

    Does nothing if the checker has zero rules (zero overhead).
    """
    if not checker._all_rules:
        return

    async def _permission_hook(event: HookEvent) -> HookResult:
        tool_name = event.payload.get("tool_name", "")
        tool_input = event.payload.get("tool_input", {})

        result = checker.check(tool_name, tool_input)

        if result.action == "deny":
            return HookResult(action="deny", reason=result.reason)

        if result.action == "ask":
            # No interactive responder available yet → fallback deny
            return HookResult(
                action="deny",
                reason=f"Permission requires confirmation (ask) but no responder is available. Rule: {result.matched_rule}",
            )

        return HookResult(action="allow")

    config = HookConfig(
        type="callable",
        callable_fn=_permission_hook,
        timeout=5,
    )
    hook_runner.register(HookEventType.PRE_TOOL_USE, config)
