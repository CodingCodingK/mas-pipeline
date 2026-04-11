"""Unit tests for notify rules (pure functions, no I/O)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.notify.rules import (
    default_rules,
    rule_agent_progress,
    rule_human_review_needed,
    rule_run_completed,
    rule_run_failed,
    rule_run_started,
)
from src.telemetry.events import (
    EVENT_TYPE_AGENT_TURN,
    EVENT_TYPE_LLM_CALL,
    EVENT_TYPE_PIPELINE,
    TelemetryEvent,
)

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def _pipeline_event(ptype: str, **payload) -> TelemetryEvent:
    return TelemetryEvent(
        event_type=EVENT_TYPE_PIPELINE,
        project_id=1,
        payload={"pipeline_event_type": ptype, "pipeline_name": "p", **payload},
        run_id="run-1",
    )


def _agent_turn_event(**payload) -> TelemetryEvent:
    base = {
        "turn_id": "t1",
        "agent_role": "writer",
        "turn_index": 3,
        "stop_reason": "done",
        "duration_ms": 100,
    }
    base.update(payload)
    return TelemetryEvent(
        event_type=EVENT_TYPE_AGENT_TURN,
        project_id=1,
        payload=base,
        run_id="run-1",
        agent_role="writer",
    )


def _llm_event() -> TelemetryEvent:
    return TelemetryEvent(
        event_type=EVENT_TYPE_LLM_CALL,
        project_id=1,
        payload={"provider": "openai", "model": "gpt-4"},
        run_id="run-1",
    )


def test_run_started() -> None:
    print("\n-- rule_run_started --")
    ev = _pipeline_event("pipeline_start")
    n = rule_run_started(ev, user_id=1)
    check("matches pipeline_start", n is not None and n.event_type == "run_started")
    check("user_id propagated", n is not None and n.user_id == 1)
    check(
        "non-match pipeline_end",
        rule_run_started(_pipeline_event("pipeline_end"), 1) is None,
    )
    check("non-match llm_call", rule_run_started(_llm_event(), 1) is None)


def test_run_completed() -> None:
    print("\n-- rule_run_completed --")
    ev_ok = _pipeline_event("pipeline_end", success=True)
    ev_fail = _pipeline_event("pipeline_end", success=False)
    ev_inferred = _pipeline_event("pipeline_end")  # no error_msg → success
    ev_error = _pipeline_event("pipeline_end", error_msg="boom")

    check(
        "matches explicit success=True",
        rule_run_completed(ev_ok, 1) is not None,
    )
    check(
        "rejects explicit success=False",
        rule_run_completed(ev_fail, 1) is None,
    )
    check(
        "infers success from missing error_msg",
        rule_run_completed(ev_inferred, 1) is not None,
    )
    check(
        "infers failure from error_msg present",
        rule_run_completed(ev_error, 1) is None,
    )
    check(
        "non-match pipeline_start",
        rule_run_completed(_pipeline_event("pipeline_start"), 1) is None,
    )


def test_run_failed() -> None:
    print("\n-- rule_run_failed --")
    check(
        "matches node_failed",
        rule_run_failed(_pipeline_event("node_failed", node_name="n1"), 1) is not None,
    )
    check(
        "matches pipeline_end success=False",
        rule_run_failed(_pipeline_event("pipeline_end", success=False), 1) is not None,
    )
    check(
        "matches pipeline_end with error_msg",
        rule_run_failed(_pipeline_event("pipeline_end", error_msg="x"), 1) is not None,
    )
    check(
        "rejects pipeline_end success=True",
        rule_run_failed(_pipeline_event("pipeline_end", success=True), 1) is None,
    )
    check(
        "rejects llm_call event",
        rule_run_failed(_llm_event(), 1) is None,
    )


def test_human_review_needed() -> None:
    print("\n-- rule_human_review_needed --")
    check(
        "matches paused + hitl reason",
        rule_human_review_needed(
            _pipeline_event("paused", reason="hitl-review", node_name="n"), 1
        )
        is not None,
    )
    check(
        "matches paused + human reason",
        rule_human_review_needed(
            _pipeline_event("paused", reason="awaiting human"), 1
        )
        is not None,
    )
    check(
        "rejects paused with unrelated reason",
        rule_human_review_needed(
            _pipeline_event("paused", reason="system-retry"), 1
        )
        is None,
    )
    check(
        "rejects pipeline_end",
        rule_human_review_needed(_pipeline_event("pipeline_end"), 1) is None,
    )


def test_agent_progress() -> None:
    print("\n-- rule_agent_progress --")
    check(
        "matches agent_turn done",
        rule_agent_progress(_agent_turn_event(), 1) is not None,
    )
    check(
        "rejects agent_turn error",
        rule_agent_progress(_agent_turn_event(stop_reason="error"), 1) is None,
    )
    check(
        "rejects llm_call",
        rule_agent_progress(_llm_event(), 1) is None,
    )


def test_default_rules() -> None:
    print("\n-- default_rules --")
    rules = default_rules()
    check("default_rules returns 5 rules", len(rules) == 5)
    names = [r.__name__ for r in rules]
    check(
        "order is started/completed/failed/review/progress",
        names
        == [
            "rule_run_started",
            "rule_run_completed",
            "rule_run_failed",
            "rule_human_review_needed",
            "rule_agent_progress",
        ],
    )


def main() -> int:
    test_run_started()
    test_run_completed()
    test_run_failed()
    test_human_review_needed()
    test_agent_progress()
    test_default_rules()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
