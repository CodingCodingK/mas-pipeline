"""Unit tests for src/tools/builtins/skill.py — SkillTool."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.skills.types import SkillDefinition
from src.tools.base import ToolContext
from src.tools.builtins.skill import SkillTool

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


def make_context(**kwargs):
    defaults = {
        "agent_id": "test-agent",
        "run_id": "run1",
        "project_id": 1,
        "abort_signal": None,
        "hook_runner": MagicMock(),
        "permission_checker": None,
    }
    defaults.update(kwargs)
    return ToolContext(**defaults)


# --- Setup ---

inline_skill = SkillDefinition(
    name="summarize",
    content="Summarize: $ARGUMENTS",
    context="inline",
)
fork_skill = SkillDefinition(
    name="research",
    content="Research $ARGUMENTS",
    context="fork",
    tools=["web_search"],
)
available = {"summarize": inline_skill, "research": fork_skill}
tool = SkillTool(available)

# --- Basic properties ---

print("=== SkillTool properties ===")
check("name is skill", tool.name == "skill")
check("has input_schema", "properties" in tool.input_schema)
check("skill_name required", "skill_name" in tool.input_schema["required"])

# --- Invalid skill_name ---

print("\n=== SkillTool: invalid skill_name ===")


async def test_invalid():
    ctx = make_context()
    r = await tool.call({"skill_name": "nonexistent"}, ctx)
    check("success False", r.success is False)
    check("not found in output", "not found" in r.output.lower())
    check("available listed", "summarize" in r.output)


asyncio.run(test_invalid())

# --- Inline dispatch ---

print("\n=== SkillTool: inline dispatch ===")


async def test_inline():
    ctx = make_context()
    r = await tool.call({"skill_name": "summarize", "args": "hello world"}, ctx)
    check("success True", r.success is True)
    check("output substituted", "Summarize: hello world" in r.output)
    check("metadata inline", r.metadata.get("status") == "inline")
    check("metadata skill_name", r.metadata.get("skill_name") == "summarize")


asyncio.run(test_inline())

# --- Fork dispatch (mocked) ---

print("\n=== SkillTool: fork dispatch ===")


async def test_fork():
    from src.agent.state import ExitReason

    mock_state = MagicMock()
    mock_state.messages = [{"role": "assistant", "content": "fork result"}]

    ctx = make_context()

    with (
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, return_value=mock_state),
        patch("src.agent.loop.run_agent_to_completion", new_callable=AsyncMock, return_value=ExitReason.COMPLETED),
        patch("src.tools.builtins.spawn_agent.extract_final_output", return_value="fork result"),
    ):
        r = await tool.call({"skill_name": "research", "args": "AI safety"}, ctx)
        check("success True", r.success is True)
        check("output from fork", "fork result" in r.output)
        check("metadata forked", r.metadata.get("status") == "forked")


asyncio.run(test_fork())

# --- Per-agent skills (different instances) ---

print("\n=== SkillTool: per-agent skills ===")

tool_a = SkillTool({"summarize": inline_skill})
tool_b = SkillTool({"research": fork_skill})


async def test_per_agent():
    ctx = make_context()
    # tool_a only has summarize
    r = await tool_a.call({"skill_name": "research"}, ctx)
    check("tool_a can't access research", r.success is False)

    r = await tool_a.call({"skill_name": "summarize", "args": "test"}, ctx)
    check("tool_a can access summarize", r.success is True)

    r = await tool_b.call({"skill_name": "summarize"}, ctx)
    check("tool_b can't access summarize", r.success is False)


asyncio.run(test_per_agent())

# --- Args default ---

print("\n=== SkillTool: args default ===")


async def test_args_default():
    ctx = make_context()
    r = await tool.call({"skill_name": "summarize"}, ctx)
    check("no args -> empty substitution", "Summarize: " in r.output)
    check("success True", r.success is True)


asyncio.run(test_args_default())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
