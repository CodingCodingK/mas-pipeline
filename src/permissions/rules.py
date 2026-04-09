"""Permission rule parsing, matching, and evaluation."""

from __future__ import annotations

import fnmatch
import re

from src.permissions.types import (
    TOOL_CONTENT_FIELD,
    PermissionMode,
    PermissionResult,
    PermissionRule,
)

# Matches "tool_name(pattern)" or bare "tool_name"
_RULE_RE = re.compile(r"^([a-z_][a-z0-9_]*)\s*(?:\((.*)?\))?\s*$", re.IGNORECASE)


def parse_rule(rule_str: str, action: str) -> PermissionRule:
    """Parse a rule string like ``bash(git *)`` into a PermissionRule.

    - ``"bash"``        → tool_name="bash", pattern=None
    - ``"bash(git *)"`` → tool_name="bash", pattern="git *"
    - ``"bash()"``      → tool_name="bash", pattern=None
    """
    m = _RULE_RE.match(rule_str.strip())
    if not m:
        raise ValueError(f"Invalid permission rule: {rule_str!r}")

    tool_name = m.group(1).lower()
    raw_pattern = m.group(2)
    pattern = raw_pattern.strip() if raw_pattern and raw_pattern.strip() else None

    return PermissionRule(tool_name=tool_name, pattern=pattern, action=action)


def rule_matches(rule: PermissionRule, tool_name: str, params: dict) -> bool:
    """Check whether *rule* applies to this tool call.

    1. tool_name must match exactly (case-insensitive).
    2. If rule has no pattern → matches all calls to that tool.
    3. If rule has a pattern → the tool must be in TOOL_CONTENT_FIELD;
       the mapped param value is tested via ``fnmatch``.
    """
    if rule.tool_name != tool_name.lower():
        return False

    if rule.pattern is None:
        return True

    # Pattern matching requires a known content field
    content_key = TOOL_CONTENT_FIELD.get(tool_name.lower())
    if content_key is None:
        return False  # unknown tool with pattern → no match

    value = params.get(content_key, "")
    if not isinstance(value, str):
        value = str(value)

    return fnmatch.fnmatch(value, rule.pattern)


def check_permission(
    tool_name: str,
    params: dict,
    rules: list[PermissionRule],
    mode: PermissionMode,
) -> PermissionResult:
    """Evaluate permission rules for a tool call.

    Priority: bypass → no-match(allow) → deny → ask → allow.
    """
    if mode == PermissionMode.BYPASS:
        return PermissionResult(action="allow")

    matched = [r for r in rules if rule_matches(r, tool_name, params)]

    if not matched:
        return PermissionResult(action="allow")

    # Deny wins
    for r in matched:
        if r.action == "deny":
            return PermissionResult(
                action="deny",
                reason=f"Denied by rule: {r.tool_name}({r.pattern or '*'})",
                matched_rule=r,
            )

    # Ask
    for r in matched:
        if r.action == "ask":
            if mode == PermissionMode.STRICT:
                return PermissionResult(
                    action="deny",
                    reason="ask converted to deny in strict mode",
                    matched_rule=r,
                )
            return PermissionResult(action="ask", matched_rule=r)

    # All allow
    return PermissionResult(action="allow")


def load_permission_rules(permissions_config: dict) -> list[PermissionRule]:
    """Parse a settings permissions dict into a flat rule list.

    Expected format::

        {"deny": ["bash(rm *)"], "allow": ["read_file"], "ask": ["shell"]}
    """
    rules: list[PermissionRule] = []
    for action in ("deny", "allow", "ask"):
        for rule_str in permissions_config.get(action, []):
            rules.append(parse_rule(rule_str, action))
    return rules
