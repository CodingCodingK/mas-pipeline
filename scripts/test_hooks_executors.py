"""Tests for hook executors: command (subprocess) and prompt (LLM mock)."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hooks.config import HookConfig
from src.hooks.executors import execute_command_hook, execute_prompt_hook
from src.hooks.types import HookEvent, HookEventType

checks: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    checks.append((name, condition))


def make_event(tool_name: str = "shell") -> HookEvent:
    return HookEvent(
        event_type=HookEventType.PRE_TOOL_USE,
        payload={"tool_name": tool_name, "tool_input": {"command": "ls"}},
    )


print("=" * 60)
print("1. Command hook: exit code 0 (allow)")
print("=" * 60)

config = HookConfig(type="command", command='python -c "print()"')
r = asyncio.run(execute_command_hook(make_event(), config))
check("1.1 Exit 0 → allow", r.action == "allow")


print()
print("=" * 60)
print("2. Command hook: exit code 0 with JSON output")
print("=" * 60)

config = HookConfig(
    type="command",
    command='python -c "import json; print(json.dumps({\'action\': \'modify\', \'updated_input\': {\'command\': \'ls -la\'}}))"',
)
r = asyncio.run(execute_command_hook(make_event(), config))
check("2.1 JSON output → modify", r.action == "modify")
check("2.2 updated_input parsed", r.updated_input == {"command": "ls -la"})


print()
print("=" * 60)
print("3. Command hook: exit code 2 (deny)")
print("=" * 60)

config = HookConfig(
    type="command",
    command='python -c "import sys; sys.stderr.write(\'forbidden\'); sys.exit(2)"',
)
r = asyncio.run(execute_command_hook(make_event(), config))
check("3.1 Exit 2 → deny", r.action == "deny")
check("3.2 Reason from stderr", "forbidden" in r.reason)


print()
print("=" * 60)
print("4. Command hook: exit code 1 (non-blocking error)")
print("=" * 60)

config = HookConfig(type="command", command='python -c "import sys; sys.exit(1)"')
r = asyncio.run(execute_command_hook(make_event(), config))
check("4.1 Exit 1 → allow (non-blocking)", r.action == "allow")


print()
print("=" * 60)
print("5. Command hook: timeout")
print("=" * 60)

config = HookConfig(type="command", command='python -c "import time; time.sleep(10)"', timeout=1)
r = asyncio.run(execute_command_hook(make_event(), config))
check("5.1 Timeout → allow (non-blocking)", r.action == "allow")


print()
print("=" * 60)
print("6. Command hook: exit 0 with non-JSON stdout")
print("=" * 60)

config = HookConfig(type="command", command='python -c "print(\'hello world\')"')
r = asyncio.run(execute_command_hook(make_event(), config))
check("6.1 Non-JSON stdout → allow", r.action == "allow")


print()
print("=" * 60)
print("7. Command hook: stdin receives JSON payload")
print("=" * 60)

# This script reads stdin and outputs the tool_name from it
config = HookConfig(
    type="command",
    command='python -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({\'additional_context\': d[\'tool_name\']}))"',
)
r = asyncio.run(execute_command_hook(make_event("shell"), config))
check("7.1 Stdin JSON received", r.additional_context == "shell")


print()
print("=" * 60)
print("8. Prompt hook: mock LLM returns allow")
print("=" * 60)


async def test_prompt_allow():
    mock_adapter = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '{"action": "allow", "additional_context": "looks safe"}'
    mock_adapter.call = AsyncMock(return_value=mock_response)

    with patch("src.llm.router.route", return_value=mock_adapter):
        config = HookConfig(type="prompt", prompt="Is this safe? $ARGUMENTS")
        r = await execute_prompt_hook(make_event(), config)
        return r


r = asyncio.run(test_prompt_allow())
check("8.1 Prompt hook → allow", r.action == "allow")
check("8.2 Additional context from LLM", r.additional_context == "looks safe")


print()
print("=" * 60)
print("9. Prompt hook: mock LLM returns deny")
print("=" * 60)


async def test_prompt_deny():
    mock_adapter = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '{"action": "deny", "reason": "dangerous command"}'
    mock_adapter.call = AsyncMock(return_value=mock_response)

    with patch("src.llm.router.route", return_value=mock_adapter):
        config = HookConfig(type="prompt", prompt="Is this safe? $ARGUMENTS")
        r = await execute_prompt_hook(make_event(), config)
        return r


r = asyncio.run(test_prompt_deny())
check("9.1 Prompt hook → deny", r.action == "deny")
check("9.2 Reason from LLM", r.reason == "dangerous command")


print()
print("=" * 60)
print("10. Prompt hook: LLM error (non-blocking)")
print("=" * 60)


async def test_prompt_error():
    with patch("src.llm.router.route", side_effect=Exception("API down")):
        config = HookConfig(type="prompt", prompt="Check $ARGUMENTS")
        r = await execute_prompt_hook(make_event(), config)
        return r


r = asyncio.run(test_prompt_error())
check("10.1 LLM error → allow (non-blocking)", r.action == "allow")


print()
print("=" * 60)
print("11. Prompt hook: $ARGUMENTS replacement")
print("=" * 60)


async def test_prompt_args():
    mock_adapter = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = '{"action": "allow"}'
    mock_adapter.call = AsyncMock(return_value=mock_response)

    with patch("src.llm.router.route", return_value=mock_adapter):
        config = HookConfig(type="prompt", prompt="Check: $ARGUMENTS")
        await execute_prompt_hook(make_event("read_file"), config)
        # Verify the LLM was called with replaced $ARGUMENTS
        call_args = mock_adapter.call.call_args[0][0]  # messages
        user_msg = call_args[1]["content"]
        return "read_file" in user_msg


check("11.1 $ARGUMENTS replaced with payload", asyncio.run(test_prompt_args()))


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
