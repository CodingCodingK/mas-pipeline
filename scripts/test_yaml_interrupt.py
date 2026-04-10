"""YAML interrupt field tests: parsing, defaults, NodeDefinition extension."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.pipeline import NodeDefinition, RouteDefinition, load_pipeline

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
    """Write YAML content to a temp file, return path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


# ── 1. Default interrupt is False ────────────────────────

print("\n=== 1. Default interrupt field ===")

yaml1 = write_yaml("""
pipeline: test
nodes:
  - name: writer
    role: writer
    output: draft
""")

p1 = load_pipeline(yaml1)
check("Default interrupt is False", p1.nodes[0].interrupt is False)
check("Default routes is empty", p1.nodes[0].routes == [])


# ── 2. Explicit interrupt: true ──────────────────────────

print("\n=== 2. Explicit interrupt: true ===")

yaml2 = write_yaml("""
pipeline: test_interrupt
nodes:
  - name: writer
    role: writer
    output: draft
  - name: reviewer
    role: reviewer
    input: [draft]
    output: review
    interrupt: true
""")

p2 = load_pipeline(yaml2)
check("writer interrupt=False", p2.nodes[0].interrupt is False)
check("reviewer interrupt=True", p2.nodes[1].interrupt is True)


# ── 3. Explicit interrupt: false ─────────────────────────

print("\n=== 3. Explicit interrupt: false ===")

yaml3 = write_yaml("""
pipeline: test
nodes:
  - name: writer
    role: writer
    output: draft
    interrupt: false
""")

p3 = load_pipeline(yaml3)
check("Explicit False stays False", p3.nodes[0].interrupt is False)


# ── 4. NodeDefinition dataclass ──────────────────────────

print("\n=== 4. NodeDefinition fields ===")

nd = NodeDefinition(name="test", role="test", output="out", interrupt=True)
check("interrupt attr exists", nd.interrupt is True)
check("routes attr default empty", nd.routes == [])

nd2 = NodeDefinition(
    name="test2", role="test2", output="out2",
    routes=[RouteDefinition(target="other", condition="ok")],
)
check("routes populated", len(nd2.routes) == 1)
check("route condition", nd2.routes[0].condition == "ok")
check("route target", nd2.routes[0].target == "other")

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed > 0:
    sys.exit(1)
else:
    print("All checks passed!")
