"""PipelineState tests: TypedDict structure and merge_dicts reducer."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.graph import PipelineState, _merge_dicts

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


# ── 1. PipelineState initialization ──────────────────────

print("\n=== 1. PipelineState initialization ===")

state: PipelineState = {
    "user_input": "Write a blog",
    "outputs": {},
    "run_id": "run-1",
    "project_id": 1,
    "permission_mode": "normal",
    "error": None,
}

check("user_input", state["user_input"] == "Write a blog")
check("outputs empty", state["outputs"] == {})
check("run_id", state["run_id"] == "run-1")
check("project_id", state["project_id"] == 1)
check("permission_mode", state["permission_mode"] == "normal")
check("error is None", state["error"] is None)

# ── 2. merge_dicts reducer ───────────────────────────────

print("\n=== 2. merge_dicts reducer ===")

left = {"a": "hello"}
right = {"b": "world"}
merged = _merge_dicts(left, right)
check("Merges two dicts", merged == {"a": "hello", "b": "world"})
check("Original left unchanged", left == {"a": "hello"})

# Overlapping keys: right wins
left2 = {"a": "old", "b": "keep"}
right2 = {"a": "new"}
merged2 = _merge_dicts(left2, right2)
check("Overlapping key overwrites", merged2["a"] == "new")
check("Non-overlapping key preserved", merged2["b"] == "keep")

# Empty dicts
check("Empty + empty = empty", _merge_dicts({}, {}) == {})
check("Empty + non-empty = right", _merge_dicts({}, {"x": "1"}) == {"x": "1"})
check("Non-empty + empty = left", _merge_dicts({"x": "1"}, {}) == {"x": "1"})

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
