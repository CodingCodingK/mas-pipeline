"""Unit tests for src/permissions/types.py — PermissionMode, PermissionRule, PermissionResult, TOOL_CONTENT_FIELD."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.permissions.types import (
    TOOL_CONTENT_FIELD,
    PermissionMode,
    PermissionResult,
    PermissionRule,
)

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


print("=== PermissionMode ===")

check("BYPASS value", PermissionMode.BYPASS == "bypass")
check("NORMAL value", PermissionMode.NORMAL == "normal")
check("STRICT value", PermissionMode.STRICT == "strict")
check("is str enum", isinstance(PermissionMode.BYPASS, str))
check("3 members", len(PermissionMode) == 3)

print("\n=== PermissionRule ===")

r = PermissionRule(tool_name="bash", pattern="git *", action="allow")
check("tool_name", r.tool_name == "bash")
check("pattern", r.pattern == "git *")
check("action", r.action == "allow")

r2 = PermissionRule(tool_name="shell", pattern=None, action="deny")
check("pattern None", r2.pattern is None)

print("\n=== PermissionResult ===")

res = PermissionResult(action="allow")
check("default reason", res.reason == "")
check("default matched_rule", res.matched_rule is None)

res2 = PermissionResult(action="deny", reason="blocked", matched_rule=r)
check("deny with reason", res2.reason == "blocked")
check("deny with rule", res2.matched_rule is r)

print("\n=== TOOL_CONTENT_FIELD ===")

check("shell→command", TOOL_CONTENT_FIELD["shell"] == "command")
check("write→file_path", TOOL_CONTENT_FIELD["write"] == "file_path")
check("read_file→file_path", TOOL_CONTENT_FIELD["read_file"] == "file_path")
check("edit→file_path", TOOL_CONTENT_FIELD["edit"] == "file_path")
check("web_search→query", TOOL_CONTENT_FIELD["web_search"] == "query")
check("spawn_agent not in map", "spawn_agent" not in TOOL_CONTENT_FIELD)
check("at least 5 entries", len(TOOL_CONTENT_FIELD) >= 5)

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
