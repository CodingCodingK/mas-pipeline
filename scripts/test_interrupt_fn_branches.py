"""Unit-test the three `_make_interrupt_fn` branches without spinning up
a full LangGraph run. We monkey-patch `src.engine.graph.interrupt` so the
inner call returns a canned feedback payload, then assert the Command /
dict shape that `interrupt_fn` produces.

Regression guard for spec `pipeline-interrupt`:
- approve  → empty-dict update with review_feedback cleared
- reject   → Command(goto="{name}_run", outputs[output]="", review_feedback=<text>)
- edit     → {outputs[output]=<edited>, review_feedback=""}

Run: python scripts/test_interrupt_fn_branches.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command

import src.engine.graph as graph_mod
from src.engine.pipeline import NodeDefinition


def _node() -> NodeDefinition:
    return NodeDefinition(name="reviewer", role="reviewer", output="review")


def _state(output_value: str = "DRAFT") -> dict:
    return {"outputs": {"review": output_value}, "review_feedback": ""}


def _run_with_feedback(feedback_payload, state: dict):
    """Patch graph.interrupt to return `feedback_payload`, invoke the
    generated interrupt_fn, and return whatever it produced.
    """
    original = graph_mod.interrupt
    graph_mod.interrupt = lambda payload: feedback_payload  # noqa: E731
    try:
        fn = graph_mod._make_interrupt_fn(_node())
        return asyncio.run(fn(state))
    finally:
        graph_mod.interrupt = original


def test_approve_clears_feedback() -> None:
    result = _run_with_feedback({"action": "approve"}, _state())
    assert isinstance(result, dict), type(result)
    assert result == {"review_feedback": ""}, result


def test_approve_bare_default_path() -> None:
    """An empty/str feedback also defaults to approve semantics."""
    result = _run_with_feedback("", _state())
    assert result == {"review_feedback": ""}, result


def test_reject_returns_command_and_clears_output() -> None:
    result = _run_with_feedback(
        {"action": "reject", "feedback": "add more examples"}, _state("OLD DRAFT")
    )
    assert isinstance(result, Command), type(result)
    assert result.goto == "reviewer_run", result.goto
    assert result.update["outputs"] == {"review": ""}, result.update
    assert result.update["review_feedback"] == "add more examples", result.update


def test_edit_replaces_output_and_clears_feedback() -> None:
    result = _run_with_feedback(
        {"action": "edit", "edited": "NEW CONTENT"}, _state("OLD DRAFT")
    )
    assert isinstance(result, dict), type(result)
    assert result["outputs"] == {"review": "NEW CONTENT"}, result
    assert result["review_feedback"] == "", result


def test_error_state_short_circuits() -> None:
    """If state already has an error, interrupt_fn must no-op."""
    st = _state()
    st["error"] = "something went wrong"
    # interrupt() must not be called in this branch — use a sentinel that
    # would fail the test if invoked.
    result = _run_with_feedback(
        {"action": "reject", "feedback": "should not reach here"}, st
    )
    assert result == {}, result


def test_legacy_string_feedback_is_treated_as_approve() -> None:
    """Bare non-empty string is legacy approve-with-comment shape."""
    result = _run_with_feedback("looks good", _state())
    assert result == {"review_feedback": ""}, result


def test_interrupt_payload_shape_is_node_and_output() -> None:
    """Regression guard for task 6.4: the payload handed to `interrupt()`
    MUST be exactly {"node": <name>, "output": <string>} so the gateway
    resume command and the frontend ResumePanel can rely on it.
    """
    captured: dict = {}

    def _capture(payload):
        captured.update(payload)
        return {"action": "approve"}

    original = graph_mod.interrupt
    graph_mod.interrupt = _capture  # type: ignore[assignment]
    try:
        fn = graph_mod._make_interrupt_fn(_node())
        asyncio.run(fn(_state("DRAFT CONTENT")))
    finally:
        graph_mod.interrupt = original

    assert set(captured.keys()) == {"node", "output"}, captured
    assert captured["node"] == "reviewer", captured
    assert captured["output"] == "DRAFT CONTENT", captured


def main() -> None:
    tests = [
        test_approve_clears_feedback,
        test_approve_bare_default_path,
        test_reject_returns_command_and_clears_output,
        test_edit_replaces_output_and_clears_feedback,
        test_error_state_short_circuits,
        test_legacy_string_feedback_is_treated_as_approve,
        test_interrupt_payload_shape_is_node_and_output,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
