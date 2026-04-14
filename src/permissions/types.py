"""Permission types: modes, rules, and check results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionMode(str, Enum):
    """Operating modes for the permission system."""

    BYPASS = "bypass"   # Skip all checks, allow everything
    NORMAL = "normal"   # Evaluate rules: allow / deny / ask
    STRICT = "strict"   # Like normal, but ask → deny (unattended mode)


@dataclass
class PermissionRule:
    """A single permission rule parsed from configuration."""

    tool_name: str          # Exact tool name (lowercase)
    pattern: str | None     # fnmatch glob for content field, None = match all
    action: str             # "allow" | "deny" | "ask"


@dataclass
class PermissionResult:
    """Outcome of a permission check."""

    action: str                             # "allow" | "deny" | "ask"
    reason: str = ""
    matched_rule: PermissionRule | None = None


# Maps tool name → the parameter field used for pattern matching.
# Tools not listed here only support tool_name-level rules (no content matching).
TOOL_CONTENT_FIELD: dict[str, str] = {
    "shell": "command",
    "write_file": "file_path",
    "write": "file_path",
    "read_file": "file_path",
    "edit": "file_path",
    "web_search": "query",
}
