"""Translate PermissionRule entries into a SandboxPolicy.

Permission is the source of truth: anything writable to Permission is
writable in the sandbox; anything readable to Permission is readable.
"""

from __future__ import annotations

from src.permissions.types import PermissionRule
from src.sandbox.types import SandboxPolicy

# Tools whose patterns name file paths and grant write access
_WRITE_TOOLS = {"write", "edit"}
# Tools whose patterns name file paths and grant read access
_READ_TOOLS = {"read_file"}

# Glob meta-characters that mark the end of a literal prefix
_GLOB_CHARS = set("*?[")


def _literal_prefix(pattern: str) -> str:
    """Reduce a glob pattern to its longest literal prefix.

    `projects/**`           → `projects`
    `src/**/*.py`           → `src`
    `data/raw`              → `data/raw`
    `**/sensitive`          → ``  (empty — skipped by caller)
    """
    out: list[str] = []
    for segment in pattern.split("/"):
        if not segment or any(c in _GLOB_CHARS for c in segment):
            break
        out.append(segment)
    return "/".join(out)


def policy_from_permission_rules(rules: list[PermissionRule]) -> SandboxPolicy:
    """Build a SandboxPolicy from the active PermissionRule set.

    Pure function: no I/O, no caching. Call on every wrap.
    """
    writable: list[str] = []
    readonly: list[str] = []

    for rule in rules:
        if rule.action != "allow" or rule.pattern is None:
            continue

        prefix = _literal_prefix(rule.pattern)
        if not prefix:
            continue

        tool = rule.tool_name.lower()
        if tool in _WRITE_TOOLS and prefix not in writable:
            writable.append(prefix)
        elif tool in _READ_TOOLS and prefix not in readonly:
            readonly.append(prefix)

    return SandboxPolicy(writable_paths=writable, readonly_paths=readonly)
