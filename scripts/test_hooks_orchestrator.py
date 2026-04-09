"""Tests for hooks integration with ToolOrchestrator."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hooks.config import HookConfig
from src.hooks.runner import HookRunner
from src.hooks.types import HookEventType
from src.llm.adapter import ToolCallRequest
from src.tools.base import Tool, ToolContext, ToolResult
from src.tools.orchestrator import ToolOrchestrator
from src.tools.registry import ToolRegistry

checks: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    checks.append((name, condition))


# --- Test tool ---

class EchoTool(Tool):
    name = "echo"
    description = "Echoes input"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        return ToolResult(output=f"echo: {params['text']}")


class FailTool(Tool):
    name = "fail_tool"
    description = "Always fails"
    input_schema = {"type": "object", "properties": {}, "required": []}

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        return ToolResult(output="something went wrong", success=False)


def make_context() -> ToolContext:
    return ToolContext(agent_id="test", run_id="run-1")


def make_registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


print("=" * 60)
print("1. No HookRunner — backward compatible")
print("=" * 60)

registry = make_registry(EchoTool())
orch = ToolOrchestrator(registry)  # No hook_runner
tc = ToolCallRequest(id="tc1", name="echo", arguments={"text": "hello"})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("1.1 Tool executes normally", results[0].output == "echo: hello")
check("1.2 Success", results[0].success is True)


print()
print("=" * 60)
print("2. PreToolUse hook: deny blocks execution")
print("=" * 60)

runner = HookRunner()
# Command hook that always exits with code 2 (deny)
runner.register(
    HookEventType.PRE_TOOL_USE,
    HookConfig(type="command", command='python -c "import sys; sys.stderr.write(\'not allowed\'); sys.exit(2)"'),
    matcher="echo",
)
registry = make_registry(EchoTool())
orch = ToolOrchestrator(registry, hook_runner=runner)
tc = ToolCallRequest(id="tc2", name="echo", arguments={"text": "hello"})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("2.1 Tool denied", results[0].success is False)
check("2.2 Deny reason in output", "not allowed" in results[0].output)


print()
print("=" * 60)
print("3. PreToolUse hook: modify replaces params")
print("=" * 60)

runner = HookRunner()
runner.register(
    HookEventType.PRE_TOOL_USE,
    HookConfig(
        type="command",
        command='python -c "import json; print(json.dumps({\'action\': \'modify\', \'updated_input\': {\'text\': \'modified\'}}))"',
    ),
    matcher="echo",
)
registry = make_registry(EchoTool())
orch = ToolOrchestrator(registry, hook_runner=runner)
tc = ToolCallRequest(id="tc3", name="echo", arguments={"text": "original"})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("3.1 Tool executed with modified params", "modified" in results[0].output)
check("3.2 Original param not used", "original" not in results[0].output)


print()
print("=" * 60)
print("4. PostToolUse hook: additional_context appended")
print("=" * 60)

runner = HookRunner()
runner.register(
    HookEventType.POST_TOOL_USE,
    HookConfig(
        type="command",
        command='python -c "import json; print(json.dumps({\'additional_context\': \'[audit: logged]\'}))"',
    ),
)
registry = make_registry(EchoTool())
orch = ToolOrchestrator(registry, hook_runner=runner)
tc = ToolCallRequest(id="tc4", name="echo", arguments={"text": "hello"})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("4.1 Output contains original", "echo: hello" in results[0].output)
check("4.2 Output contains additional_context", "[audit: logged]" in results[0].output)


print()
print("=" * 60)
print("5. PostToolUseFailure hook: fires on tool failure")
print("=" * 60)

# Track if the failure hook was called by checking its output
runner = HookRunner()
runner.register(
    HookEventType.POST_TOOL_USE_FAILURE,
    HookConfig(
        type="command",
        command='python -c "import json; print(json.dumps({\'additional_context\': \'[failure noted]\'}))"',
    ),
)
registry = make_registry(FailTool())
orch = ToolOrchestrator(registry, hook_runner=runner)
tc = ToolCallRequest(id="tc5", name="fail_tool", arguments={})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("5.1 Tool failed", results[0].success is False)
check("5.2 Failure hook context appended", "[failure noted]" in results[0].output)


print()
print("=" * 60)
print("6. Matcher filters: hook only fires for matching tool")
print("=" * 60)

runner = HookRunner()
runner.register(
    HookEventType.PRE_TOOL_USE,
    HookConfig(type="command", command='python -c "import sys; sys.exit(2)"'),
    matcher="shell",  # Only matches "shell", not "echo"
)
registry = make_registry(EchoTool())
orch = ToolOrchestrator(registry, hook_runner=runner)
tc = ToolCallRequest(id="tc6", name="echo", arguments={"text": "hello"})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("6.1 Non-matching tool not blocked", results[0].success is True)
check("6.2 Tool executed normally", "echo: hello" in results[0].output)


print()
print("=" * 60)
print("7. Multiple hooks: deny wins")
print("=" * 60)

runner = HookRunner()
runner.register(
    HookEventType.PRE_TOOL_USE,
    HookConfig(type="command", command='python -c "import json; print(json.dumps({\'action\': \'allow\'}))"'),
    matcher="echo",
)
runner.register(
    HookEventType.PRE_TOOL_USE,
    HookConfig(type="command", command='python -c "import sys; sys.stderr.write(\'blocked\'); sys.exit(2)"'),
    matcher="echo",
)
registry = make_registry(EchoTool())
orch = ToolOrchestrator(registry, hook_runner=runner)
tc = ToolCallRequest(id="tc7", name="echo", arguments={"text": "hello"})
results = asyncio.run(orch.dispatch([tc], make_context()))
check("7.1 Deny wins over allow", results[0].success is False)
check("7.2 Blocked reason present", "blocked" in results[0].output.lower())


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
