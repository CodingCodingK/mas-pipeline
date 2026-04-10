"""PermissionChecker: stateful wrapper around the rule engine for a single agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.permissions.rules import check_permission

if TYPE_CHECKING:
    from src.permissions.types import PermissionMode, PermissionResult, PermissionRule


class PermissionChecker:
    """Encapsulates permission rules + mode for one agent's lifetime."""

    def __init__(
        self,
        rules: list[PermissionRule],
        mode: PermissionMode,
        parent_deny_rules: list[PermissionRule] | None = None,
    ) -> None:
        # Merge parent deny rules (prepend so they are checked first)
        self._own_rules = list(rules)
        self._parent_deny = list(parent_deny_rules) if parent_deny_rules else []
        self._all_rules = self._parent_deny + self._own_rules
        self._mode = mode

    def check(self, tool_name: str, params: dict) -> PermissionResult:
        """Check whether *tool_name(params)* is permitted."""
        return check_permission(tool_name, params, self._all_rules, self._mode)

    def get_deny_rules(self) -> list[PermissionRule]:
        """Return all deny rules (own + inherited) for passing to child agents."""
        return [r for r in self._all_rules if r.action == "deny"]

    def get_rules(self) -> list[PermissionRule]:
        """Return all active rules (own + inherited) for sandbox policy derivation."""
        return list(self._all_rules)
