"""Telemetry event dataclasses.

Each event carries the common envelope (ts, event_type, project_id, run_id,
session_id, agent_role) plus an event-type-specific payload dict. The collector
serialises the payload into the `telemetry_events.payload` JSONB column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TelemetryEvent:
    """Envelope shared by every event type.

    payload is built by the collector's record_* method from the event-specific
    fields — see the LLMCallEvent / ToolCallEvent / ... dataclasses below.
    """

    event_type: str
    project_id: int
    payload: dict[str, Any]
    ts: datetime = field(default_factory=_utcnow)
    run_id: str | None = None
    session_id: int | None = None
    agent_role: str | None = None


# ── Event-type-specific payload builders ───────────────────────────────
#
# These are thin dataclasses that the collector uses to validate shape before
# dropping into the JSONB payload. They are NOT separately persisted.


@dataclass
class LLMCallEvent:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    latency_ms: int
    finish_reason: str
    cost_usd: float | None
    turn_id: str | None
    parent_turn_id: str | None


@dataclass
class ToolCallEvent:
    tool_name: str
    args_preview: str
    duration_ms: int
    success: bool
    error_type: str | None
    error_msg: str | None
    parent_turn_id: str | None


@dataclass
class AgentTurnEvent:
    turn_id: str
    agent_role: str
    turn_index: int
    started_at: str
    ended_at: str
    duration_ms: int
    message_count_delta: int
    stop_reason: str
    input_preview: str
    output_preview: str
    spawned_by_spawn_id: str | None


@dataclass
class AgentSpawnEvent:
    spawn_id: str
    parent_role: str
    child_role: str
    task_preview: str
    parent_turn_id: str | None


@dataclass
class PipelineEvent:
    pipeline_event_type: str  # pipeline_start/node_start/node_end/node_failed/paused/resumed/pipeline_end
    pipeline_name: str
    node_name: str | None
    duration_ms: int | None
    error_msg: str | None


@dataclass
class SessionEvent:
    session_event_type: str  # created/first_message/idle_exit/max_age_exit/shutdown_exit
    channel: str | None
    mode: str


@dataclass
class HookEvent:
    hook_type: str
    decision: str
    latency_ms: int
    rule_matched: str | None
    parent_turn_id: str | None


@dataclass
class ErrorEvent:
    source: str  # llm/tool/pipeline/gateway/session/hook
    error_type: str
    message: str  # truncated to 500 chars
    stacktrace_hash: str
    context: dict[str, Any]
    parent_turn_id: str | None


EVENT_TYPE_LLM_CALL = "llm_call"
EVENT_TYPE_TOOL_CALL = "tool_call"
EVENT_TYPE_AGENT_TURN = "agent_turn"
EVENT_TYPE_AGENT_SPAWN = "agent_spawn"
EVENT_TYPE_PIPELINE = "pipeline_event"
EVENT_TYPE_SESSION = "session_event"
EVENT_TYPE_HOOK = "hook_event"
EVENT_TYPE_ERROR = "error"
