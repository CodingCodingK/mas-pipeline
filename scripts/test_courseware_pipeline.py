"""Courseware exam pipeline tests: YAML loading, role parsing, dependency inference, tool pool."""

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

pipeline = load_pipeline(str(PIPELINES_DIR / "courseware_exam.yaml"))

check("Pipeline name", pipeline.name == "courseware_exam")
check("Has 4 nodes", len(pipeline.nodes) == 4)
check(
    "Node names",
    [n.name for n in pipeline.nodes] == ["parser", "analyzer", "exam_generator", "exam_reviewer"],
)
check(
    "Node roles",
    [n.role for n in pipeline.nodes] == ["parser", "analyzer", "exam_generator", "exam_reviewer"],
)
check(
    "Node outputs",
    [n.output for n in pipeline.nodes] == ["parsed_content", "knowledge_points", "exam_draft", "final_exam"],
)

# ── 2. Dependency inference ──────────────────────────────

print("\n=== 2. Dependency inference ===")

check("Parser has no deps", pipeline.dependencies["parser"] == set())
check("Analyzer depends on parser", pipeline.dependencies["analyzer"] == {"parser"})
check("Exam_generator depends on analyzer", pipeline.dependencies["exam_generator"] == {"analyzer"})
check("Exam_reviewer depends on exam_generator", pipeline.dependencies["exam_reviewer"] == {"exam_generator"})

# Output → node mapping
check("parsed_content → parser", pipeline.output_to_node["parsed_content"] == "parser")
check("knowledge_points → analyzer", pipeline.output_to_node["knowledge_points"] == "analyzer")
check("exam_draft → exam_generator", pipeline.output_to_node["exam_draft"] == "exam_generator")
check("final_exam → exam_reviewer", pipeline.output_to_node["final_exam"] == "exam_reviewer")

# ── 3. Role files ────────────────────────────────────────

print("\n=== 3. Role files ===")

all_tools = get_all_tools()

for role_name, expected_tools, expected_tier in [
    ("parser", ["search_docs", "read_file"], "strong"),
    ("analyzer", [], "medium"),
    ("exam_generator", ["search_docs", "read_file"], "medium"),
    ("exam_reviewer", ["web_search"], "medium"),
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

check("search_docs in get_all_tools()", "search_docs" in all_tools)
check("read_file in get_all_tools()", "read_file" in all_tools)
check("Total tools >= 7", len(all_tools) >= 7, f"got {len(all_tools)}: {list(all_tools.keys())}")

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
