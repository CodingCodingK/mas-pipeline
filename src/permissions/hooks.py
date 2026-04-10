"""Permission ↔ Hook bridge: register permission rules as a PreToolUse hook."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.hooks.config import HookConfig
from src.hooks.types import HookEvent, HookEventType, HookResult
from src.permissions.types import PermissionMode

if TYPE_CHECKING:
    from src.hooks.runner import HookRunner
    from src.permissions.checker import PermissionChecker


def register_permission_hooks(
    hook_runner: HookRunner,
    checker: PermissionChecker,
) -> None:
    """Register the permission checker as a callable PreToolUse hook.

    Also enforces sandbox escape-hatch policy: shell calls passing
    `dangerously_disable_sandbox=true` SHALL require user confirmation
    (treated as "ask" in NORMAL, denied outright in STRICT, allowed in BYPASS).
    """
    if not checker._all_rules:
        # Zero rules → user trusts the agent fully → skip the bridge entirely.
        # The dangerously_disable_sandbox escape hatch only matters when the
        # user has configured permission constraints in the first place.
        return

    async def _permission_hook(event: HookEvent) -> HookResult:
        # Sandbox escape hatch is checked first — it overrides allow rules.
        sandbox_result = _check_sandbox_escape(event, checker._mode)
        if sandbox_result is not None:
            return sandbox_result

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

    hook_runner.register(
        HookEventType.PRE_TOOL_USE,
        HookConfig(type="callable", callable_fn=_permission_hook, timeout=5),
    )


def _check_sandbox_escape(
    event: HookEvent, mode: PermissionMode
) -> HookResult | None:
    """Return a HookResult if the call is an unsandboxed shell escape, else None."""
    tool_name = event.payload.get("tool_name", "")
    tool_input = event.payload.get("tool_input", {}) or {}
    if tool_name != "shell" or not tool_input.get("dangerously_disable_sandbox"):
        return None
    if mode == PermissionMode.BYPASS:
        return HookResult(action="allow")
    if mode == PermissionMode.STRICT:
        return HookResult(
            action="deny",
            reason="dangerously_disable_sandbox=true is not allowed in STRICT mode",
        )
    # NORMAL → ask, falls back to deny when no responder is wired up
    return HookResult(
        action="deny",
        reason="dangerously_disable_sandbox=true requires user confirmation (ask)",
    )
