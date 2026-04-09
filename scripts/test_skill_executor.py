"""Unit tests for src/skills/executor.py — substitute_variables, execute_inline, execute_fork."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.skills.executor import execute_fork, execute_inline, substitute_variables
from src.skills.types import SkillDefinition, SkillResult

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


# --- substitute_variables ---

print("=== substitute_variables: all vars ===")

ctx = {"project_id": 42, "agent_id": "run1:researcher", "skill_dir": "/skills"}
result = substitute_variables(
    "Topic: $ARGUMENTS, project=${PROJECT_ID}, agent=${AGENT_ID}, dir=${SKILL_DIR}",
    "Python async",
    ctx,
)
check("ARGUMENTS replaced", "Topic: Python async" in result)
check("PROJECT_ID replaced", "project=42" in result)
check("AGENT_ID replaced", "agent=run1:researcher" in result)
check("SKILL_DIR replaced", "dir=/skills" in result)

print("\n=== substitute_variables: missing values ===")

result = substitute_variables("id=${PROJECT_ID}, agent=${AGENT_ID}", "", {})
check("missing project_id -> empty", "id=," in result)
check("missing agent_id -> empty", "agent=" in result)

print("\n=== substitute_variables: no vars ===")

result = substitute_variables("plain text no vars", "args", {})
check("unchanged text", result == "plain text no vars")

print("\n=== substitute_variables: empty args ===")

result = substitute_variables("Research: $ARGUMENTS end", "", {})
check("empty args replaced", result == "Research:  end")

# --- execute_inline ---

print("\n=== execute_inline ===")

skill = SkillDefinition(
    name="summarize",
    content="Summarize: $ARGUMENTS",
    context="inline",
)
ctx = {"project_id": 1, "agent_id": "a1"}
r = execute_inline(skill, "some long text", ctx)
check("returns SkillResult", isinstance(r, SkillResult))
check("mode is inline", r.mode == "inline")
check("output substituted", r.output == "Summarize: some long text")
check("skill_name", r.skill_name == "summarize")
check("success True", r.success is True)

# --- execute_fork (mocked) ---

print("\n=== execute_fork: success ===")


async def test_fork_success():
    from src.agent.state import ExitReason

    skill = SkillDefinition(
        name="research",
        content="Research $ARGUMENTS",
        context="fork",
        tools=["web_search"],
    )

    mock_state = MagicMock()
    mock_state.messages = [
        {"role": "assistant", "content": "Research result here"}
    ]

    with (
        patch("src.agent.factory.create_agent", new_callable=AsyncMock, return_value=mock_state),
        patch("src.agent.loop.run_agent_to_completion", new_callable=AsyncMock, return_value=ExitReason.COMPLETED),
        patch("src.tools.builtins.spawn_agent.extract_final_output", return_value="Research result here"),
    ):
        r = await execute_fork(skill, "Python GIL", {
            "project_id": 1,
            "run_id": "run1",
            "permission_mode": None,
        })
        check("mode fork", r.mode == "fork")
        check("success True", r.success is True)
        check("output captured", r.output == "Research result here")
        check("skill_name", r.skill_name == "research")


asyncio.run(test_fork_success())

print("\n=== execute_fork: error ===")


async def test_fork_error():
    skill = SkillDefinition(name="bad", content="fail", context="fork")

    with patch("src.agent.factory.create_agent", side_effect=RuntimeError("boom")):
        r = await execute_fork(skill, "", {"permission_mode": None})
        check("success False", r.success is False)
        check("error in output", "boom" in r.output)
        check("mode fork", r.mode == "fork")


asyncio.run(test_fork_error())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
