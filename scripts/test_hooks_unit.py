"""Unit tests for hook types, events, results, and aggregation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hooks.types import HookEvent, HookEventType, HookResult, aggregate_results

checks: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    checks.append((name, condition))


print("=" * 60)
print("1. HookEventType enum")
print("=" * 60)

check("1.1 PRE_TOOL_USE is string", HookEventType.PRE_TOOL_USE == "pre_tool_use")
check("1.2 POST_TOOL_USE is string", HookEventType.POST_TOOL_USE == "post_tool_use")
check("1.3 POST_TOOL_USE_FAILURE is string", HookEventType.POST_TOOL_USE_FAILURE == "post_tool_use_failure")
check("1.4 SESSION_START is string", HookEventType.SESSION_START == "session_start")
check("1.5 SESSION_END is string", HookEventType.SESSION_END == "session_end")
check("1.6 SUBAGENT_START is string", HookEventType.SUBAGENT_START == "subagent_start")
check("1.7 SUBAGENT_END is string", HookEventType.SUBAGENT_END == "subagent_end")
check("1.8 PIPELINE_START is string", HookEventType.PIPELINE_START == "pipeline_start")
check("1.9 PIPELINE_END is string", HookEventType.PIPELINE_END == "pipeline_end")
check("1.10 Exactly 9 members", len(HookEventType) == 9)

print()
print("=" * 60)
print("2. HookEvent construction")
print("=" * 60)

event = HookEvent(
    event_type=HookEventType.PRE_TOOL_USE,
    payload={"tool_name": "shell", "tool_input": {"command": "ls"}},
)
check("2.1 Event type correct", event.event_type == HookEventType.PRE_TOOL_USE)
check("2.2 Payload has tool_name", event.payload["tool_name"] == "shell")
check("2.3 Timestamp auto-set", event.timestamp > 0)

print()
print("=" * 60)
print("3. HookResult defaults")
print("=" * 60)

default = HookResult()
check("3.1 Default action is allow", default.action == "allow")
check("3.2 Default reason is empty", default.reason == "")
check("3.3 Default updated_input is None", default.updated_input is None)
check("3.4 Default additional_context is empty", default.additional_context == "")

print()
print("=" * 60)
print("4. aggregate_results")
print("=" * 60)

# Empty list
check("4.1 Empty list returns allow", aggregate_results([]).action == "allow")

# All allow
r = aggregate_results([HookResult(), HookResult()])
check("4.2 All allow → allow", r.action == "allow")

# One deny among allows
r = aggregate_results([
    HookResult(action="allow"),
    HookResult(action="deny", reason="forbidden"),
    HookResult(action="allow"),
])
check("4.3 One deny → deny", r.action == "deny")
check("4.4 Deny reason preserved", r.reason == "forbidden")

# Modify takes last
r = aggregate_results([
    HookResult(action="modify", updated_input={"a": 1}),
    HookResult(action="modify", updated_input={"b": 2}),
])
check("4.5 Last modify wins", r.action == "modify")
check("4.6 Last modify input used", r.updated_input == {"b": 2})

# Deny wins over modify
r = aggregate_results([
    HookResult(action="modify", updated_input={"a": 1}),
    HookResult(action="deny", reason="nope"),
])
check("4.7 Deny wins over modify", r.action == "deny")

# Additional context concatenation
r = aggregate_results([
    HookResult(additional_context="note A"),
    HookResult(additional_context="note B"),
])
check("4.8 Contexts concatenated", "note A" in r.additional_context and "note B" in r.additional_context)

# Context preserved on deny
r = aggregate_results([
    HookResult(action="allow", additional_context="ctx1"),
    HookResult(action="deny", reason="no", additional_context="ctx2"),
])
check("4.9 Context preserved on deny", "ctx1" in r.additional_context and "ctx2" in r.additional_context)

print()
print("=" * 60)
print("5. Matcher logic")
print("=" * 60)

from src.hooks.runner import _matcher_matches

check("5.1 None matches everything", _matcher_matches(None, "shell"))
check("5.2 Empty string matches everything", _matcher_matches("", "shell"))
check("5.3 Exact match", _matcher_matches("shell", "shell"))
check("5.4 No match", not _matcher_matches("shell", "read_file"))
check("5.5 Pipe-separated match", _matcher_matches("shell|spawn_agent", "spawn_agent"))
check("5.6 Pipe-separated no match", not _matcher_matches("shell|spawn_agent", "read_file"))

# Summary
print()
print("=" * 60)
passed = sum(1 for _, ok in checks if ok)
total = len(checks)
print(f"Results: {passed}/{total} checks passed")
if passed < total:
    failed = [name for name, ok in checks if not ok]
    print(f"Failed: {failed}")
    sys.exit(1)
print("All checks passed!")
