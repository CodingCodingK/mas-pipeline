"""Unit tests for src/skills/types.py — SkillDefinition, SkillResult."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


print("=== SkillDefinition defaults ===")

sd = SkillDefinition(name="test", content="body")
check("name preserved", sd.name == "test")
check("content preserved", sd.content == "body")
check("description default empty", sd.description == "")
check("when_to_use default empty", sd.when_to_use == "")
check("context default inline", sd.context == "inline")
check("model_tier default inherit", sd.model_tier == "inherit")
check("tools default empty list", sd.tools == [])
check("always default False", sd.always is False)
check("arguments default empty", sd.arguments == "")

print("\n=== SkillDefinition with all fields ===")

sd2 = SkillDefinition(
    name="research",
    content="do research on $ARGUMENTS",
    description="deep research",
    when_to_use="when researching",
    context="fork",
    model_tier="medium",
    tools=["web_search", "read_file"],
    always=True,
    arguments="topic",
)
check("name", sd2.name == "research")
check("content", sd2.content == "do research on $ARGUMENTS")
check("description", sd2.description == "deep research")
check("when_to_use", sd2.when_to_use == "when researching")
check("context fork", sd2.context == "fork")
check("model_tier medium", sd2.model_tier == "medium")
check("tools list", sd2.tools == ["web_search", "read_file"])
check("always True", sd2.always is True)
check("arguments", sd2.arguments == "topic")

print("\n=== SkillDefinition tools isolation ===")

sd3 = SkillDefinition(name="a", content="x")
sd4 = SkillDefinition(name="b", content="y")
sd3.tools.append("shell")
check("tools not shared between instances", sd4.tools == [])

print("\n=== SkillResult defaults ===")

sr = SkillResult(mode="inline", output="hello", skill_name="test")
check("mode preserved", sr.mode == "inline")
check("output preserved", sr.output == "hello")
check("skill_name preserved", sr.skill_name == "test")
check("success default True", sr.success is True)

print("\n=== SkillResult with success=False ===")

sr2 = SkillResult(mode="fork", output="error", skill_name="bad", success=False)
check("success False", sr2.success is False)
check("mode fork", sr2.mode == "fork")

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
