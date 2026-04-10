"""Conditional routing tests: route_fn logic for substring matching + error priority."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.graph import PipelineState

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


# Simulate the routing function logic from _add_route_edges
# (We test the pure logic rather than going through build_graph)

def make_route_fn(output_name: str, conditions: list[tuple[str, str]], default_target: str | None):
    """Replicate the route_fn logic from graph.py."""
    def route_fn(state: PipelineState) -> str:
        if state.get("error"):
            return "__end__"
        content = state["outputs"].get(output_name, "")
        for condition_str, target_name in conditions:
            if condition_str in content:
                return target_name
        if default_target:
            return default_target
        return "__end__"
    return route_fn


# ── 1. Condition matches ─────────────────────────────────

print("\n=== 1. Condition matches ===")

# Note: condition order matters — "不通过" must come before "通过"
# because "通过" is a substring of "不通过"
fn = make_route_fn("review_result", [("不通过", "revise"), ("通过", "publish")], "revise")

state_pass: PipelineState = {
    "user_input": "", "outputs": {"review_result": "审核结果：通过"}, "run_id": "",
    "project_id": 1, "permission_mode": "normal", "error": None,
}
check("'通过' matches publish", fn(state_pass) == "publish")

state_fail: PipelineState = {
    "user_input": "", "outputs": {"review_result": "审核结果：不通过，需要修改"}, "run_id": "",
    "project_id": 1, "permission_mode": "normal", "error": None,
}
check("'不通过' matches revise", fn(state_fail) == "revise")


# ── 2. No condition matches → default ───────────────────

print("\n=== 2. No match → default ===")

state_none: PipelineState = {
    "user_input": "", "outputs": {"review_result": "需要大幅修改"}, "run_id": "",
    "project_id": 1, "permission_mode": "normal", "error": None,
}
check("No match goes to default", fn(state_none) == "revise")


# ── 3. No default → END ─────────────────────────────────

print("\n=== 3. No default → END ===")

fn_no_default = make_route_fn("result", [("ok", "next")], None)

state_no_match: PipelineState = {
    "user_input": "", "outputs": {"result": "something else"}, "run_id": "",
    "project_id": 1, "permission_mode": "normal", "error": None,
}
check("No match no default → END", fn_no_default(state_no_match) == "__end__")


# ── 4. Error overrides routes ───────────────────────────

print("\n=== 4. Error overrides routes ===")

state_error: PipelineState = {
    "user_input": "", "outputs": {"review_result": "通过"}, "run_id": "",
    "project_id": 1, "permission_mode": "normal", "error": "node crashed",
}
check("Error routes to END even with matching condition", fn(state_error) == "__end__")


# ── 5. First match wins ─────────────────────────────────

print("\n=== 5. First match wins ===")

fn2 = make_route_fn("out", [("match", "first"), ("match", "second")], "default")

state_multi: PipelineState = {
    "user_input": "", "outputs": {"out": "this has match in it"}, "run_id": "",
    "project_id": 1, "permission_mode": "normal", "error": None,
}
check("First matching condition wins", fn2(state_multi) == "first")


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
