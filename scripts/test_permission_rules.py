"""Unit tests for src/permissions/rules.py — parse_rule, rule_matches, check_permission, load_permission_rules."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.permissions.rules import (
    check_permission,
    load_permission_rules,
    parse_rule,
    rule_matches,
)
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


# ── parse_rule ──────────────────────────────────────────

print("=== parse_rule ===")

r = parse_rule("bash(git *)", "allow")
check("with pattern: tool_name", r.tool_name == "bash")
check("with pattern: pattern", r.pattern == "git *")
check("with pattern: action", r.action == "allow")

r2 = parse_rule("shell", "deny")
check("no pattern: tool_name", r2.tool_name == "shell")
check("no pattern: pattern None", r2.pattern is None)
check("no pattern: action", r2.action == "deny")

r3 = parse_rule("bash()", "allow")
check("empty parens: pattern None", r3.pattern is None)

r4 = parse_rule("Write(/etc/*)", "deny")
check("case insensitive tool_name", r4.tool_name == "write")
check("preserves pattern case", r4.pattern == "/etc/*")

try:
    parse_rule("", "allow")
    check("empty string raises", False)
except ValueError:
    check("empty string raises", True)

try:
    parse_rule("123invalid", "allow")
    check("invalid name raises", False)
except ValueError:
    check("invalid name raises", True)


# ── rule_matches ────────────────────────────────────────

print("\n=== rule_matches ===")

check("name match, no pattern", rule_matches(
    PermissionRule("shell", None, "deny"), "shell", {}
))
check("name mismatch", not rule_matches(
    PermissionRule("bash", None, "deny"), "write", {}
))
check("pattern match", rule_matches(
    PermissionRule("shell", "git *", "allow"), "shell", {"command": "git status"}
))
check("pattern no match", not rule_matches(
    PermissionRule("shell", "git *", "allow"), "shell", {"command": "rm -rf /"}
))
check("unknown tool with pattern → False", not rule_matches(
    PermissionRule("spawn_agent", "researcher", "deny"), "spawn_agent", {"role": "researcher"}
))
check("known tool, missing param → no match", not rule_matches(
    PermissionRule("shell", "git *", "allow"), "shell", {}
))
check("file path glob", rule_matches(
    PermissionRule("write", "/etc/*", "deny"), "write", {"file_path": "/etc/passwd"}
))
check("file path glob no match", not rule_matches(
    PermissionRule("write", "/etc/*", "deny"), "write", {"file_path": "/home/user/file.txt"}
))


# ── check_permission ───────────────────────────────────

print("\n=== check_permission ===")

rules = [
    PermissionRule("shell", None, "allow"),
    PermissionRule("shell", "rm *", "deny"),
    PermissionRule("write", "/etc/*", "deny"),
    PermissionRule("read_file", "*.env", "ask"),
]

res = check_permission("shell", {"command": "ls"}, rules, PermissionMode.BYPASS)
check("bypass → allow", res.action == "allow")

res = check_permission("unknown_tool", {}, rules, PermissionMode.NORMAL)
check("no match → allow", res.action == "allow")

res = check_permission("shell", {"command": "rm -rf /"}, rules, PermissionMode.NORMAL)
check("deny priority over allow", res.action == "deny")
check("deny has reason", "rm" in res.reason.lower() or "deny" in res.reason.lower())
check("deny has matched_rule", res.matched_rule is not None)

res = check_permission("shell", {"command": "ls"}, rules, PermissionMode.NORMAL)
check("allow when only allow matches", res.action == "allow")

res = check_permission("read_file", {"file_path": "secrets.env"}, rules, PermissionMode.NORMAL)
check("ask in normal mode", res.action == "ask")

res = check_permission("read_file", {"file_path": "secrets.env"}, rules, PermissionMode.STRICT)
check("ask→deny in strict mode", res.action == "deny")
check("strict reason", "strict" in res.reason.lower())

res = check_permission("shell", {}, [], PermissionMode.NORMAL)
check("empty rules → allow", res.action == "allow")

# Multiple deny — first matched deny used
multi_deny = [
    PermissionRule("shell", "rm *", "deny"),
    PermissionRule("shell", "rm -rf *", "deny"),
]
res = check_permission("shell", {"command": "rm -rf /"}, multi_deny, PermissionMode.NORMAL)
check("multiple deny → still deny", res.action == "deny")


# ── load_permission_rules ──────────────────────────────

print("\n=== load_permission_rules ===")

config = {"deny": ["bash(rm *)"], "allow": ["read_file"], "ask": ["shell"]}
loaded = load_permission_rules(config)
check("mixed config: 3 rules", len(loaded) == 3)
check("deny rule first", loaded[0].action == "deny")
check("allow rule second", loaded[1].action == "allow")
check("ask rule third", loaded[2].action == "ask")

check("empty config", load_permission_rules({}) == [])
check("missing keys", len(load_permission_rules({"deny": ["shell"]})) == 1)

# Invalid rule in list
try:
    load_permission_rules({"deny": [""]})
    check("invalid rule raises", False)
except ValueError:
    check("invalid rule raises", True)

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
