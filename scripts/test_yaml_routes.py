"""YAML routes field tests: parsing, validation, RouteDefinition construction."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.pipeline import RouteDefinition, _parse_routes, _validate_routes, NodeDefinition, load_pipeline

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


def write_yaml(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


# ── 1. _parse_routes ─────────────────────────────────────

print("\n=== 1. _parse_routes ===")

routes = _parse_routes([
    {"condition": "通过", "target": "publish"},
    {"condition": "不通过", "target": "revise"},
    {"default": "revise"},
], "reviewer")

check("Parses 3 routes", len(routes) == 3)
check("First route condition", routes[0].condition == "通过")
check("First route target", routes[0].target == "publish")
check("First route not default", routes[0].is_default is False)
check("Third route is default", routes[2].is_default is True)
check("Default route target", routes[2].target == "revise")
check("Default route no condition", routes[2].condition is None)

# Invalid route format
try:
    _parse_routes([{"invalid": "field"}], "test")
    check("Invalid route raises", False, "no exception")
except ValueError as e:
    check("Invalid route raises ValueError", "condition" in str(e))


# ── 2. _validate_routes ─────────────────────────────────

print("\n=== 2. _validate_routes ===")

node_names = {"reviewer", "publish", "revise"}

# Valid: conditions + default
valid_node = NodeDefinition(
    name="reviewer", role="reviewer", output="review",
    routes=[
        RouteDefinition(target="publish", condition="通过"),
        RouteDefinition(target="revise", is_default=True),
    ],
)
try:
    _validate_routes(valid_node, node_names)
    check("Valid routes pass validation", True)
except ValueError:
    check("Valid routes pass validation", False, "unexpected error")

# Invalid: multiple defaults
multi_default = NodeDefinition(
    name="reviewer", role="reviewer", output="review",
    routes=[
        RouteDefinition(target="publish", is_default=True),
        RouteDefinition(target="revise", is_default=True),
    ],
)
try:
    _validate_routes(multi_default, node_names)
    check("Multiple defaults rejected", False, "no exception")
except ValueError as e:
    check("Multiple defaults rejected", "at most one default" in str(e))

# Invalid: conditions without default
no_default = NodeDefinition(
    name="reviewer", role="reviewer", output="review",
    routes=[
        RouteDefinition(target="publish", condition="通过"),
    ],
)
try:
    _validate_routes(no_default, node_names)
    check("No default rejected", False, "no exception")
except ValueError as e:
    check("No default rejected", "must have a default" in str(e))

# Invalid: target not a valid node
bad_target = NodeDefinition(
    name="reviewer", role="reviewer", output="review",
    routes=[
        RouteDefinition(target="nonexistent", is_default=True),
    ],
)
try:
    _validate_routes(bad_target, node_names)
    check("Bad target rejected", False, "no exception")
except ValueError as e:
    check("Bad target rejected", "not a valid node" in str(e))


# ── 3. Full YAML routes parsing ──────────────────────────

print("\n=== 3. YAML routes parsing ===")

yaml_routes = write_yaml("""
pipeline: test_routes
nodes:
  - name: reviewer
    role: reviewer
    output: review_result
    routes:
      - condition: "通过"
        target: publish
      - condition: "不通过"
        target: revise
      - default: revise

  - name: publish
    role: publisher
    input: [review_result]
    output: published

  - name: revise
    role: writer
    input: [review_result]
    output: revised
""")

p = load_pipeline(yaml_routes)
reviewer = p.nodes[0]
check("Reviewer has 3 routes", len(reviewer.routes) == 3)
check("Publish node has no routes", len(p.nodes[1].routes) == 0)
check("Revise node has no routes", len(p.nodes[2].routes) == 0)


# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
