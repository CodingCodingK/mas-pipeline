"""Unit tests for src/agent/context.py — _skill_layer, build_system_prompt with skills."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.context import _skill_layer, build_system_prompt
from src.skills.types import SkillDefinition

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


# --- _skill_layer ---

print("=== _skill_layer: empty/None ===")
check("None returns None", _skill_layer(None) is None)
check("empty list returns None", _skill_layer([]) is None)

print("\n=== _skill_layer: always-on only ===")

always_skill = SkillDefinition(
    name="coding-style",
    content="Always follow PEP 8.",
    always=True,
)
result = _skill_layer([always_skill])
check("contains Always-On header", "# Always-On Skills" in result)
check("contains skill content", "Always follow PEP 8." in result)
check("no Available Skills header", "# Available Skills" not in result)

print("\n=== _skill_layer: on-demand only ===")

on_demand = SkillDefinition(
    name="research",
    content="Research $ARGUMENTS thoroughly.",
    description="Deep research on a topic",
    when_to_use="When researching",
    arguments="topic",
    always=False,
)
result = _skill_layer([on_demand])
check("contains Available Skills header", "# Available Skills" in result)
check("contains skills XML tag", "<skills>" in result)
check("contains skill name attr", 'name="research"' in result)
check("contains description", "Deep research on a topic" in result)
check("contains when-to-use", "When researching" in result)
check("contains arguments", "topic" in result)
check("contains usage hint", "skill" in result.lower())
check("no Always-On header", "# Always-On Skills" not in result)

print("\n=== _skill_layer: mixed ===")

result = _skill_layer([always_skill, on_demand])
check("contains both headers", "# Always-On Skills" in result and "# Available Skills" in result)
check("always content present", "Always follow PEP 8." in result)
check("on-demand XML present", 'name="research"' in result)

print("\n=== _skill_layer: on-demand without optional fields ===")

minimal = SkillDefinition(name="basic", content="do basic stuff", always=False)
result = _skill_layer([minimal])
check("contains skill name", 'name="basic"' in result)
# No description/when_to_use/arguments tags since they're empty
check("no empty description tag", "<description></description>" not in result)

# --- build_system_prompt with skills ---

print("\n=== build_system_prompt with skills ===")

prompt = build_system_prompt("You are a researcher.", skill_definitions=[always_skill, on_demand])
check("contains role", "You are a researcher." in prompt)
check("contains always skill", "Always follow PEP 8." in prompt)
check("contains on-demand skill", 'name="research"' in prompt)
check("contains environment", "# Environment" in prompt)

print("\n=== build_system_prompt without skills ===")

prompt = build_system_prompt("You are a writer.")
check("contains role", "You are a writer." in prompt)
check("no skills section", "# Always-On Skills" not in prompt)
check("no available skills", "# Available Skills" not in prompt)

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
