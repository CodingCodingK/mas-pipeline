"""Unit tests for telemetry query layer pure functions.

DB round-trips are covered in integration tests (test_telemetry_integration.py);
here we exercise the aggregation/tree algorithms against hand-crafted event
lists so they stay fast and deterministic.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telemetry.query import _build_tree, _summarise

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


def _evt(event_type: str, payload: dict, ts: datetime, **extras) -> dict:
    base = {
        "id": extras.pop("id", 0),
        "ts": ts,
        "event_type": event_type,
        "project_id": extras.pop("project_id", 1),
        "run_id": extras.pop("run_id", "run-1"),
        "session_id": extras.pop("session_id", None),
        "agent_role": extras.pop("agent_role", None),
        "payload": payload,
    }
    base.update(extras)
    return base


# ── _summarise ────────────────────────────────────────────


def test_summarise_counts_and_totals() -> None:
    print("\n[_summarise]")
    t0 = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        _evt("llm_call", {
            "input_tokens": 100, "output_tokens": 50,
            "cost_usd": 0.012, "latency_ms": 800,
        }, t0),
        _evt("llm_call", {
            "input_tokens": 200, "output_tokens": 75,
            "cost_usd": 0.018, "latency_ms": 1200,
        }, t0 + timedelta(seconds=5)),
        _evt("tool_call", {"tool_name": "shell", "duration_ms": 150, "success": True},
             t0 + timedelta(seconds=10)),
        _evt("error", {"source": "tool", "error_type": "RuntimeError"},
             t0 + timedelta(seconds=11)),
    ]
    s = _summarise(events)
    check("event_counts has 3 types", len(s["event_counts"]) == 3)
    check("total_events == 4", s["total_events"] == 4)
    check("llm_calls == 2", s["llm_calls"] == 2)
    check("tool_calls == 1", s["tool_calls"] == 1)
    check("errors == 1", s["errors"] == 1)
    check("total_input_tokens == 300", s["total_input_tokens"] == 300)
    check("total_output_tokens == 125", s["total_output_tokens"] == 125)
    check("total_cost_usd == 0.03", abs(s["total_cost_usd"] - 0.03) < 1e-9)
    check("total_llm_latency_ms == 2000", s["total_llm_latency_ms"] == 2000)
    check("duration_ms == 11000", s["duration_ms"] == 11000)
    check("started_at is t0", s["started_at"] == t0.isoformat())


def test_summarise_empty() -> None:
    print("\n[_summarise empty]")
    s = _summarise([])
    check("empty totals zero", s["total_events"] == 0 and s["llm_calls"] == 0)
    check("duration None", s["duration_ms"] is None)


# ── _build_tree ───────────────────────────────────────────


def test_tree_coordinator_with_children() -> None:
    print("\n[_build_tree coordinator + 2 spawned children]")
    t0 = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        # parent turn
        _evt("agent_turn", {
            "turn_id": "T1", "agent_role": "coordinator",
            "turn_index": 1, "spawned_by_spawn_id": None,
            "duration_ms": 500, "stop_reason": "done",
        }, t0),
        # parent's llm_call
        _evt("llm_call", {
            "parent_turn_id": "T1", "input_tokens": 10, "output_tokens": 5,
            "cost_usd": 0.001, "latency_ms": 300,
        }, t0 + timedelta(seconds=1)),
        # parent's spawn events
        _evt("agent_spawn", {
            "spawn_id": "S1", "parent_turn_id": "T1",
            "parent_role": "coordinator", "child_role": "researcher",
            "task_preview": "gather",
        }, t0 + timedelta(seconds=2)),
        _evt("agent_spawn", {
            "spawn_id": "S2", "parent_turn_id": "T1",
            "parent_role": "coordinator", "child_role": "writer",
            "task_preview": "compose",
        }, t0 + timedelta(seconds=3)),
        # child turns
        _evt("agent_turn", {
            "turn_id": "T2", "agent_role": "researcher",
            "turn_index": 1, "spawned_by_spawn_id": "S1",
            "duration_ms": 300, "stop_reason": "done",
        }, t0 + timedelta(seconds=5)),
        _evt("llm_call", {
            "parent_turn_id": "T2", "input_tokens": 20, "output_tokens": 10,
            "cost_usd": 0.002, "latency_ms": 200,
        }, t0 + timedelta(seconds=6)),
        _evt("agent_turn", {
            "turn_id": "T3", "agent_role": "writer",
            "turn_index": 1, "spawned_by_spawn_id": "S2",
            "duration_ms": 400, "stop_reason": "done",
        }, t0 + timedelta(seconds=8)),
    ]

    tree = _build_tree(events)
    check("1 root turn", len(tree["roots"]) == 1)
    root = tree["roots"][0]
    check("root is T1", root["turn_id"] == "T1")
    check("root has 1 direct llm child", len(root["children"]) == 1)
    check("root has 2 child turns", len(root["child_turns"]) == 2)
    child_ids = {c["turn_id"] for c in root["child_turns"]}
    check("child turns are T2 & T3", child_ids == {"T2", "T3"})
    # researcher child should have its own llm_call
    researcher = next(c for c in root["child_turns"] if c["turn_id"] == "T2")
    check("researcher has 1 llm child", len(researcher["children"]) == 1)
    check("no orphans", len(tree["orphans"]) == 0)
    check("2 spawn records", len(tree["spawns"]) == 2)


def test_tree_orphan_child() -> None:
    print("\n[_build_tree orphan when parent missing]")
    t0 = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        _evt("agent_spawn", {
            "spawn_id": "S9", "parent_turn_id": "TMISSING",
            "parent_role": "coordinator", "child_role": "researcher",
            "task_preview": "x",
        }, t0),
        _evt("agent_turn", {
            "turn_id": "TX", "agent_role": "researcher",
            "turn_index": 1, "spawned_by_spawn_id": "S9",
            "duration_ms": 100, "stop_reason": "done",
        }, t0 + timedelta(seconds=1)),
    ]
    tree = _build_tree(events)
    check("orphan captured", len(tree["orphans"]) == 1)
    check("no roots", len(tree["roots"]) == 0)


def test_tree_unspawned_is_root() -> None:
    print("\n[_build_tree top-level turn without spawn is root]")
    t0 = datetime(2026, 4, 11, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        _evt("agent_turn", {
            "turn_id": "T1", "agent_role": "assistant",
            "turn_index": 1, "spawned_by_spawn_id": None,
            "duration_ms": 100, "stop_reason": "done",
        }, t0),
    ]
    tree = _build_tree(events)
    check("1 root", len(tree["roots"]) == 1)
    check("root is T1", tree["roots"][0]["turn_id"] == "T1")


def main() -> int:
    print("=" * 60)
    print("telemetry query pure-function tests")
    print("=" * 60)
    test_summarise_counts_and_totals()
    test_summarise_empty()
    test_tree_coordinator_with_children()
    test_tree_orphan_child()
    test_tree_unspawned_is_root()
    print(f"\n{'=' * 60}")
    print(f"passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
