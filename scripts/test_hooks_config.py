"""Tests for hook configuration loading and validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hooks.config import (
    HookConfig,
    HookConfigError,
    load_hooks_from_frontmatter,
    load_hooks_from_settings,
    validate_hook_config,
)
from src.hooks.types import HookEventType

checks: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    checks.append((name, condition))


print("=" * 60)
print("1. HookConfig validation")
print("=" * 60)

# Valid command hook
try:
    validate_hook_config(HookConfig(type="command", command="python validate.py"))
    check("1.1 Valid command hook passes", True)
except HookConfigError:
    check("1.1 Valid command hook passes", False)

# Valid prompt hook
try:
    validate_hook_config(HookConfig(type="prompt", prompt="Is this safe? $ARGUMENTS"))
    check("1.2 Valid prompt hook passes", True)
except HookConfigError:
    check("1.2 Valid prompt hook passes", False)

# Invalid type
try:
    validate_hook_config(HookConfig(type="http", command="curl"))
    check("1.3 Invalid type rejected", False)
except HookConfigError:
    check("1.3 Invalid type rejected", True)

# Missing command field
try:
    validate_hook_config(HookConfig(type="command"))
    check("1.4 Missing command rejected", False)
except HookConfigError:
    check("1.4 Missing command rejected", True)

# Missing prompt field
try:
    validate_hook_config(HookConfig(type="prompt"))
    check("1.5 Missing prompt rejected", False)
except HookConfigError:
    check("1.5 Missing prompt rejected", True)

# Default timeout
c = HookConfig(type="command", command="echo hi")
check("1.6 Default timeout is 30", c.timeout == 30)


print()
print("=" * 60)
print("2. Load hooks from settings.yaml format")
print("=" * 60)

settings_hooks = {
    "pre_tool_use": [
        {
            "matcher": "shell",
            "hooks": [
                {"type": "command", "command": "python validate.py", "timeout": 10},
            ],
        },
        {
            "matcher": "spawn_agent",
            "hooks": [
                {"type": "prompt", "prompt": "Is this safe? $ARGUMENTS"},
            ],
        },
    ],
    "post_tool_use": [
        {
            "hooks": [
                {"type": "command", "command": "python audit.py"},
            ],
        },
    ],
}

result = load_hooks_from_settings(settings_hooks)
check("2.1 Loaded 3 hooks", len(result) == 3)

# First hook: pre_tool_use / shell / command
et, matcher, config = result[0]
check("2.2 First is PRE_TOOL_USE", et == HookEventType.PRE_TOOL_USE)
check("2.3 First matcher is 'shell'", matcher == "shell")
check("2.4 First is command type", config.type == "command")
check("2.5 First timeout is 10", config.timeout == 10)

# Second hook: pre_tool_use / spawn_agent / prompt
et, matcher, config = result[1]
check("2.6 Second is PRE_TOOL_USE", et == HookEventType.PRE_TOOL_USE)
check("2.7 Second matcher is 'spawn_agent'", matcher == "spawn_agent")
check("2.8 Second is prompt type", config.type == "prompt")

# Third hook: post_tool_use / no matcher / command
et, matcher, config = result[2]
check("2.9 Third is POST_TOOL_USE", et == HookEventType.POST_TOOL_USE)
check("2.10 Third matcher is None", matcher is None)


print()
print("=" * 60)
print("3. Load hooks from agent frontmatter")
print("=" * 60)

frontmatter_hooks = {
    "pre_tool_use": [
        {
            "matcher": "shell",
            "hooks": [
                {"type": "command", "command": "exit 2"},
            ],
        },
    ],
}

result = load_hooks_from_frontmatter(frontmatter_hooks)
check("3.1 Loaded 1 hook from frontmatter", len(result) == 1)
et, matcher, config = result[0]
check("3.2 Event type correct", et == HookEventType.PRE_TOOL_USE)
check("3.3 Matcher correct", matcher == "shell")
check("3.4 Command correct", config.command == "exit 2")


print()
print("=" * 60)
print("4. Empty/missing config")
print("=" * 60)

check("4.1 Empty dict returns empty", load_hooks_from_settings({}) == [])
check("4.2 None returns empty", load_hooks_from_settings(None) == [])
check("4.3 Non-dict returns empty", load_hooks_from_settings("invalid") == [])


print()
print("=" * 60)
print("5. Invalid config entries are skipped")
print("=" * 60)

# Invalid hook type in settings → should be skipped (logged)
settings_hooks = {
    "pre_tool_use": [
        {
            "hooks": [
                {"type": "http", "command": "curl"},  # invalid type
                {"type": "command", "command": "python ok.py"},  # valid
            ],
        },
    ],
}
result = load_hooks_from_settings(settings_hooks)
check("5.1 Invalid hook skipped, valid loaded", len(result) == 1)
check("5.2 Valid hook is the command one", result[0][2].command == "python ok.py")


print()
print("=" * 60)
print("6. Unknown event type raises error")
print("=" * 60)

settings_hooks = {
    "unknown_event": [
        {"hooks": [{"type": "command", "command": "echo"}]},
    ],
}
try:
    load_hooks_from_settings(settings_hooks)
    check("6.1 Unknown event type raises", False)
except HookConfigError:
    check("6.1 Unknown event type raises", True)


print()
print("=" * 60)
print("7. Settings model has hooks field")
print("=" * 60)

from src.project.config import Settings

s = Settings()
check("7.1 Settings has hooks field", hasattr(s, "hooks"))
check("7.2 Default hooks is empty dict", s.hooks == {})


print()
print("=" * 60)
print("8. Global + role merge in HookRunner")
print("=" * 60)

from src.hooks.runner import HookRunner

runner = HookRunner()

# Global hook
global_hooks = load_hooks_from_settings({
    "pre_tool_use": [{"matcher": "shell", "hooks": [{"type": "command", "command": "echo global"}]}],
})
for et, matcher, config in global_hooks:
    runner.register(et, config, matcher=matcher)

# Role hook
role_hooks = load_hooks_from_frontmatter({
    "pre_tool_use": [{"matcher": "shell", "hooks": [{"type": "command", "command": "echo role"}]}],
})
for et, matcher, config in role_hooks:
    runner.register(et, config, matcher=matcher)

# Both should be registered
all_pre = runner._hooks.get(HookEventType.PRE_TOOL_USE, [])
check("8.1 Both global and role hooks registered", len(all_pre) == 2)
commands = [h.config.command for h in all_pre]
check("8.2 Global hook present", "echo global" in commands)
check("8.3 Role hook present", "echo role" in commands)


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
