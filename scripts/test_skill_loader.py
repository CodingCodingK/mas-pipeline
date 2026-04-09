"""Unit tests for src/skills/loader.py — load_skill, load_skills, _parse_frontmatter."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.skills.loader import load_skill, load_skills

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


# --- load_skill ---

print("=== load_skill: full frontmatter ===")

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "research.md"
    p.write_text(
        "---\n"
        "name: research\n"
        "description: deep research\n"
        "when_to_use: when researching\n"
        "context: fork\n"
        "model_tier: medium\n"
        "tools: [web_search, read_file]\n"
        "always: false\n"
        "arguments: topic\n"
        "---\n"
        "\n"
        "Research $ARGUMENTS thoroughly.\n",
        encoding="utf-8",
    )
    s = load_skill(p)
    check("name from frontmatter", s.name == "research")
    check("description", s.description == "deep research")
    check("when_to_use", s.when_to_use == "when researching")
    check("context fork", s.context == "fork")
    check("model_tier medium", s.model_tier == "medium")
    check("tools parsed", s.tools == ["web_search", "read_file"])
    check("always False", s.always is False)
    check("arguments", s.arguments == "topic")
    check("content is body", "Research $ARGUMENTS thoroughly." in s.content)

print("\n=== load_skill: minimal frontmatter ===")

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "quick.md"
    p.write_text("---\n---\n\nJust the body.\n", encoding="utf-8")
    s = load_skill(p)
    check("name defaults to stem", s.name == "quick")
    check("description empty", s.description == "")
    check("context default inline", s.context == "inline")
    check("model_tier default inherit", s.model_tier == "inherit")
    check("tools default empty", s.tools == [])
    check("content is body", s.content == "Just the body.")

print("\n=== load_skill: no frontmatter ===")

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / "plain.md"
    p.write_text("No frontmatter here, just text.", encoding="utf-8")
    s = load_skill(p)
    check("name from filename", s.name == "plain")
    check("content is full text", s.content == "No frontmatter here, just text.")
    check("context default", s.context == "inline")

print("\n=== load_skill: file not found ===")

try:
    load_skill(Path("/nonexistent/skill.md"))
    check("raises FileNotFoundError", False)
except FileNotFoundError:
    check("raises FileNotFoundError", True)

# --- load_skills ---

print("\n=== load_skills: multiple files ===")

with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "alpha.md").write_text(
        "---\nname: alpha\n---\nAlpha body.", encoding="utf-8"
    )
    (Path(tmp) / "beta.md").write_text(
        "---\nname: beta\ncontext: fork\n---\nBeta body.", encoding="utf-8"
    )
    # non-md file should be ignored
    (Path(tmp) / "readme.txt").write_text("ignore me", encoding="utf-8")

    skills = load_skills(Path(tmp))
    check("two skills loaded", len(skills) == 2)
    check("alpha in dict", "alpha" in skills)
    check("beta in dict", "beta" in skills)
    check("beta is fork", skills["beta"].context == "fork")

print("\n=== load_skills: empty directory ===")

with tempfile.TemporaryDirectory() as tmp:
    skills = load_skills(Path(tmp))
    check("empty dict", skills == {})

print("\n=== load_skills: nonexistent directory ===")

skills = load_skills(Path("/nonexistent/dir"))
check("returns empty dict", skills == {})

print("\n=== load_skills: default directory ===")

# This loads from project's skills/ dir
skills = load_skills()
check("loads preset skills", len(skills) >= 2)
check("research exists", "research" in skills)
check("summarize exists", "summarize" in skills)

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
