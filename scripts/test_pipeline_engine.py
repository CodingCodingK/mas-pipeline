"""Pipeline engine tests: YAML loading, dependency inference, validation, and reactive scheduling."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.pipeline import (
    NodeDefinition,
    PipelineDefinition,
    PipelineResult,
    _build_task_description,
    _check_no_cycles,
    _find_terminal_outputs,
    _mark_downstream_skipped,
    load_pipeline,
)

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


# ── 1. YAML Loading ──────────────────────────────────────

print("\n=== 1. YAML Loading ===")

# Load linear pipeline
p = load_pipeline(str(Path(__file__).parent.parent / "pipelines" / "test_linear.yaml"))
check("Linear pipeline name", p.name == "test_linear")
check("Linear pipeline has 3 nodes", len(p.nodes) == 3)
check("Linear nodes correct", [n.name for n in p.nodes] == ["researcher", "writer", "reviewer"])

# Load parallel pipeline
p2 = load_pipeline(str(Path(__file__).parent.parent / "pipelines" / "test_parallel.yaml"))
check("Parallel pipeline name", p2.name == "test_parallel")
check("Parallel pipeline has 6 nodes", len(p2.nodes) == 6)

# ── 2. Dependency Inference ───────────────────────────────

print("\n=== 2. Dependency Inference ===")

# Linear dependencies
check("researcher has no deps", p.dependencies["researcher"] == set())
check("writer depends on researcher", p.dependencies["writer"] == {"researcher"})
check("reviewer depends on writer", p.dependencies["reviewer"] == {"writer"})

# Parallel dependencies
check("analyst has no deps", p2.dependencies["analyst"] == set())
check("fact_checker has no deps", p2.dependencies["fact_checker"] == set())
check("writer depends on researcher+analyst",
      p2.dependencies["writer"] == {"researcher", "analyst"})
check("reviewer depends on writer+fact_checker",
      p2.dependencies["reviewer"] == {"writer", "fact_checker"})
check("editor depends on reviewer (via draft+feedback)",
      p2.dependencies["editor"] == {"writer", "reviewer"})

# output_to_node mapping
check("output_to_node findings→researcher", p2.output_to_node["findings"] == "researcher")
check("output_to_node draft→writer", p2.output_to_node["draft"] == "writer")

# ── 3. Validation ─────────────────────────────────────────

print("\n=== 3. Validation ===")

# Duplicate output
dup_yaml = """
pipeline: dup_test
nodes:
  - name: a
    role: general
    output: same
  - name: b
    role: general
    output: same
"""
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    f.write(dup_yaml)
    dup_path = f.name

try:
    load_pipeline(dup_path)
    check("Duplicate output raises", False, "Should have raised ValueError")
except ValueError as e:
    check("Duplicate output raises", "Duplicate output" in str(e))

# Invalid input reference
bad_ref_yaml = """
pipeline: bad_ref
nodes:
  - name: a
    role: general
    output: x
  - name: b
    role: general
    input: [nonexistent]
    output: y
"""
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    f.write(bad_ref_yaml)
    bad_ref_path = f.name

try:
    load_pipeline(bad_ref_path)
    check("Invalid input reference raises", False, "Should have raised ValueError")
except ValueError as e:
    check("Invalid input reference raises", "unknown input" in str(e))

# Cycle detection
cycle_yaml = """
pipeline: cycle
nodes:
  - name: a
    role: general
    input: [y]
    output: x
  - name: b
    role: general
    input: [x]
    output: y
"""
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    f.write(cycle_yaml)
    cycle_path = f.name

try:
    load_pipeline(cycle_path)
    check("Cycle detection raises", False, "Should have raised ValueError")
except ValueError as e:
    check("Cycle detection raises", "cycle" in str(e))

# Missing pipeline field
no_pipeline_yaml = """
nodes:
  - name: a
    role: general
    output: x
"""
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    f.write(no_pipeline_yaml)
    no_pipeline_path = f.name

try:
    load_pipeline(no_pipeline_path)
    check("Missing pipeline field raises", False, "Should have raised ValueError")
except ValueError as e:
    check("Missing pipeline field raises", "pipeline" in str(e).lower())

# File not found
try:
    load_pipeline("/nonexistent/path.yaml")
    check("File not found raises", False, "Should have raised FileNotFoundError")
except FileNotFoundError:
    check("File not found raises", True)

# ── 4. Task Description Building ──────────────────────────

print("\n=== 4. Task Description Building ===")

entry_node = NodeDefinition(name="r", role="general", output="findings")
desc = _build_task_description(entry_node, {}, "Write about Rust")
check("Entry node gets user_input", desc == "Write about Rust")

dep_node = NodeDefinition(name="w", role="general", output="draft", input=["findings", "analysis"])
outputs = {"findings": "Research data here", "analysis": "Analysis data here"}
desc2 = _build_task_description(dep_node, outputs, "Write about Rust")
check("Non-entry node has input sections", "## findings" in desc2 and "## analysis" in desc2)
check("Non-entry node has content", "Research data here" in desc2 and "Analysis data here" in desc2)
check("Non-entry node has user_input", "Write about Rust" in desc2)

# ── 5. Terminal Node Detection ────────────────────────────

print("\n=== 5. Terminal Node Detection ===")

terminals = _find_terminal_outputs(p)
check("Linear terminal is feedback", terminals == ["feedback"])

terminals2 = _find_terminal_outputs(p2)
check("Parallel terminal is final_article", terminals2 == ["final_article"])

# ── 6. Downstream Skip Marking ────────────────────────────

print("\n=== 6. Downstream Skip Marking ===")

pending = {"writer", "reviewer", "editor"}
skipped: set[str] = set()
_mark_downstream_skipped(
    "researcher",
    p2.dependencies,
    {n.name: n for n in p2.nodes},
    pending,
    skipped,
)
check("writer skipped (depends on researcher)", "writer" in skipped)
check("reviewer skipped (depends on writer→researcher)", "reviewer" in skipped)
check("editor skipped (depends on reviewer→writer→researcher)", "editor" in skipped)

# Unrelated branch not affected
pending2 = {"writer", "fact_checker", "reviewer", "editor"}
skipped2: set[str] = set()
_mark_downstream_skipped(
    "analyst",
    p2.dependencies,
    {n.name: n for n in p2.nodes},
    pending2,
    skipped2,
)
check("writer skipped (depends on analyst)", "writer" in skipped2)
check("fact_checker NOT skipped (no dependency on analyst)", "fact_checker" not in skipped2)

# ── Summary ───────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
