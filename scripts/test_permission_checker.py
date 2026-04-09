"""Unit tests for src/permissions/checker.py — PermissionChecker class."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.permissions.checker import PermissionChecker
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


print("=== PermissionChecker ===")

# Basic check delegation
rules = [
    PermissionRule("shell", None, "allow"),
    PermissionRule("shell", "rm *", "deny"),
]
checker = PermissionChecker(rules, PermissionMode.NORMAL)

res = checker.check("shell", {"command": "ls"})
check("allow through", res.action == "allow")

res = checker.check("shell", {"command": "rm -rf /"})
check("deny through", res.action == "deny")

res = checker.check("unknown", {})
check("no match → allow", res.action == "allow")

# get_deny_rules
deny_rules = checker.get_deny_rules()
check("get_deny_rules count", len(deny_rules) == 1)
check("get_deny_rules content", deny_rules[0].pattern == "rm *")

# Parent deny merge
print("\n=== Parent Deny Inheritance ===")

parent_deny = [PermissionRule("shell", "rm *", "deny")]
child_rules = [PermissionRule("web_search", None, "deny")]

child_checker = PermissionChecker(child_rules, PermissionMode.NORMAL, parent_deny_rules=parent_deny)

res = child_checker.check("shell", {"command": "rm -rf /"})
check("parent deny blocks child", res.action == "deny")

res = child_checker.check("web_search", {"query": "test"})
check("child own deny works", res.action == "deny")

res = child_checker.check("read_file", {"file_path": "test.txt"})
check("no match → allow", res.action == "allow")

child_deny = child_checker.get_deny_rules()
check("merged deny count", len(child_deny) == 2)

# Parent allow NOT inherited (only deny)
parent_allow = [PermissionRule("shell", "git *", "allow")]
child2 = PermissionChecker([], PermissionMode.NORMAL, parent_deny_rules=parent_allow)
# parent_deny_rules should only contain deny rules (caller extracts via get_deny_rules)
# but even if passed, allow rules get merged but don't affect default-allow behavior
res = child2.check("shell", {"command": "git status"})
check("default allow (not from parent)", res.action == "allow")

# Bypass mode
bypass = PermissionChecker(rules, PermissionMode.BYPASS)
res = bypass.check("shell", {"command": "rm -rf /"})
check("bypass skips deny", res.action == "allow")

# Strict mode
strict_rules = [PermissionRule("read_file", "*.env", "ask")]
strict = PermissionChecker(strict_rules, PermissionMode.STRICT)
res = strict.check("read_file", {"file_path": "secrets.env"})
check("strict: ask→deny", res.action == "deny")

# Empty rules
empty = PermissionChecker([], PermissionMode.NORMAL)
res = empty.check("shell", {"command": "anything"})
check("empty rules → allow", res.action == "allow")
check("empty get_deny_rules", len(empty.get_deny_rules()) == 0)

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
