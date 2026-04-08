"""Blog pipeline tests: YAML loading, role parsing, and pipeline structure validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.pipeline import load_pipeline
from src.agent.context import parse_role_file
from src.tools.builtins import get_all_tools

passed = 0
failed = 0

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
PIPELINES_DIR = Path(__file__).resolve().parent.parent / "pipelines"


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


# ── 1. YAML loading ──────────────────────────────────────

print("\n=== 1. Pipeline YAML loading ===")

pipeline = load_pipeline(str(PIPELINES_DIR / "blog_generation.yaml"))

check("Pipeline name", pipeline.name == "blog_generation")
check("Has 3 nodes", len(pipeline.nodes) == 3)
check("Node names", [n.name for n in pipeline.nodes] == ["researcher", "writer", "reviewer"])
check("Node roles", [n.role for n in pipeline.nodes] == ["researcher", "writer", "reviewer"])
check("Node outputs", [n.output for n in pipeline.nodes] == ["research", "draft", "final_post"])

# ── 2. Dependency inference ──────────────────────────────

print("\n=== 2. Dependency inference ===")

check("Researcher has no deps", pipeline.dependencies["researcher"] == set())
check("Writer depends on researcher", pipeline.dependencies["writer"] == {"researcher"})
check("Reviewer depends on writer", pipeline.dependencies["reviewer"] == {"writer"})

# Output → node mapping
check("research → researcher", pipeline.output_to_node["research"] == "researcher")
check("draft → writer", pipeline.output_to_node["draft"] == "writer")
check("final_post → reviewer", pipeline.output_to_node["final_post"] == "reviewer")

# ── 3. Role files ────────────────────────────────────────

print("\n=== 3. Role files ===")

all_tools = get_all_tools()

for role_name, expected_tools, expected_tier in [
    ("researcher", ["web_search", "read_file"], "medium"),
    ("writer", ["read_file"], "medium"),
    ("reviewer", [], "medium"),
]:
    role_path = AGENTS_DIR / f"{role_name}.md"
    check(f"{role_name}.md exists", role_path.is_file())

    metadata, body = parse_role_file(str(role_path))
    check(f"{role_name} model_tier={expected_tier}", metadata.get("model_tier") == expected_tier)
    check(f"{role_name} tools={expected_tools}", metadata.get("tools", []) == expected_tools)
    check(f"{role_name} has body", len(body) > 50)

    # Verify all requested tools exist in global pool
    for t in expected_tools:
        check(f"{role_name} tool '{t}' exists in pool", t in all_tools)

# ── 4. Global tool pool ─────────────────────────────────

print("\n=== 4. Global tool pool ===")

check("web_search in get_all_tools()", "web_search" in all_tools)
check("Total tools = 7", len(all_tools) == 7, f"got {len(all_tools)}: {list(all_tools.keys())}")

# ── 5. Pipeline ↔ Role integration ──────────────────────

print("\n=== 5. Pipeline-Role integration ===")

for node in pipeline.nodes:
    role_path = AGENTS_DIR / f"{node.role}.md"
    check(f"Node '{node.name}' role file exists", role_path.is_file(), f"missing {role_path}")

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
