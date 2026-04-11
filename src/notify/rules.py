"""Rule set deriving Notifications from TelemetryEvents.

Rules are pure synchronous callables. A rule inspects one event and returns
either a constructed `Notification` or `None` if the event does not match.
Rules MUST NOT query the database or mutate module state — if a rule needs
per-user info, the caller (Notifier._loop) must resolve it up front and pass
the resulting user_id as the second argument.

Adding a new rule
-----------------
1. Write `def rule_<name>(event: TelemetryEvent, user_id: int) -> Notification | None:`
2. Return `Notification(...)` on match, `None` otherwise
3. Append to the list returned by `default_rules()` (order = evaluation order;
   a single event can match multiple rules — they all fire independently)
4. Add a scenario to `scripts/test_notify_rules.py` covering match + non-match
"""

from __future__ import annotations

from typing import Callable

from src.notify.events import Notification
from src.telemetry.events import (
    EVENT_TYPE_AGENT_TURN,
    EVENT_TYPE_PIPELINE,
    TelemetryEvent,
)

Rule = Callable[[TelemetryEvent, int], "Notification | None"]


def _pipeline_name(event: TelemetryEvent) -> str:
    return str(event.payload.get("pipeline_name") or "pipeline")


def _run_label(event: TelemetryEvent) -> str:
    name = _pipeline_name(event)
    run_id = event.run_id or "?"
    return f"{name} ({run_id})"


def _is_pipeline_end(event: TelemetryEvent) -> bool:
    return (
        event.event_type == EVENT_TYPE_PIPELINE
        and event.payload.get("pipeline_event_type") == "pipeline_end"
    )


def _succeeded(event: TelemetryEvent) -> bool:
    """True if pipeline_end payload indicates success.

    Prefers explicit `success` field (forward-compatible). Falls back to
    absence of `error_msg` for current emission sites.
    """
    if "success" in event.payload:
        return bool(event.payload.get("success"))
    return event.payload.get("error_msg") in (None, "")


def rule_run_started(event: TelemetryEvent, user_id: int) -> Notification | None:
    if event.event_type != EVENT_TYPE_PIPELINE:
        return None
    if event.payload.get("pipeline_event_type") != "pipeline_start":
        return None
    return Notification(
        event_type="run_started",
        user_id=user_id,
        title="Run started",
        body=f"Pipeline run started: {_run_label(event)}",
        payload={
            "run_id": event.run_id,
            "project_id": event.project_id,
            "pipeline_name": _pipeline_name(event),
        },
    )


def rule_run_completed(event: TelemetryEvent, user_id: int) -> Notification | None:
    if not _is_pipeline_end(event):
        return None
    if not _succeeded(event):
        return None
    return Notification(
        event_type="run_completed",
        user_id=user_id,
        title="Run completed",
        body=f"Pipeline run completed: {_run_label(event)}",
        payload={
            "run_id": event.run_id,
            "project_id": event.project_id,
            "pipeline_name": _pipeline_name(event),
            "duration_ms": event.payload.get("duration_ms"),
        },
    )


def rule_run_failed(event: TelemetryEvent, user_id: int) -> Notification | None:
    if event.event_type != EVENT_TYPE_PIPELINE:
        return None
    ptype = event.payload.get("pipeline_event_type")
    if ptype == "node_failed":
        return Notification(
            event_type="run_failed",
            user_id=user_id,
            title="Node failed",
            body=(
                f"Node {event.payload.get('node_name') or '?'} failed in "
                f"{_run_label(event)}"
            ),
            payload={
                "run_id": event.run_id,
                "project_id": event.project_id,
                "pipeline_name": _pipeline_name(event),
                "node_name": event.payload.get("node_name"),
                "error_msg": event.payload.get("error_msg"),
            },
        )
    if ptype == "pipeline_end" and not _succeeded(event):
        return Notification(
            event_type="run_failed",
            user_id=user_id,
            title="Run failed",
            body=f"Pipeline run failed: {_run_label(event)}",
            payload={
                "run_id": event.run_id,
                "project_id": event.project_id,
                "pipeline_name": _pipeline_name(event),
                "error_msg": event.payload.get("error_msg"),
            },
        )
    return None


def rule_human_review_needed(
    event: TelemetryEvent, user_id: int
) -> Notification | None:
    if event.event_type != EVENT_TYPE_PIPELINE:
        return None
    if event.payload.get("pipeline_event_type") != "paused":
        return None
    reason = str(event.payload.get("reason") or "")
    if "hitl" not in reason.lower() and "human" not in reason.lower():
        return None
    return Notification(
        event_type="human_review_needed",
        user_id=user_id,
        title="Human review needed",
        body=(
            f"{_run_label(event)} paused for review at node "
            f"{event.payload.get('node_name') or '?'}"
        ),
        payload={
            "run_id": event.run_id,
            "project_id": event.project_id,
            "pipeline_name": _pipeline_name(event),
            "node_name": event.payload.get("node_name"),
            "reason": reason,
        },
    )


def rule_agent_progress(
    event: TelemetryEvent, user_id: int
) -> Notification | None:
    if event.event_type != EVENT_TYPE_AGENT_TURN:
        return None
    if event.payload.get("stop_reason") == "error":
        return None
    role = event.payload.get("agent_role") or event.agent_role or "agent"
    return Notification(
        event_type="agent_progress",
        user_id=user_id,
        title="Agent progress",
        body=f"{role} finished turn {event.payload.get('turn_index', '?')}",
        payload={
            "run_id": event.run_id,
            "project_id": event.project_id,
            "agent_role": role,
            "turn_id": event.payload.get("turn_id"),
            "turn_index": event.payload.get("turn_index"),
            "duration_ms": event.payload.get("duration_ms"),
        },
    )


def default_rules() -> list[Rule]:
    return [
        rule_run_started,
        rule_run_completed,
        rule_run_failed,
        rule_human_review_needed,
        rule_agent_progress,
    ]
