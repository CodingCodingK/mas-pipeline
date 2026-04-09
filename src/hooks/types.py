"""Hook event types, event payloads, and result structures."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class HookEventType(str, Enum):
    """All supported hook events."""

    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    PIPELINE_START = "pipeline_start"
    PIPELINE_END = "pipeline_end"


@dataclass
class HookEvent:
    """Carries event type and payload to hook executors."""

    event_type: HookEventType
    payload: dict
    timestamp: float = field(default_factory=time.time)


@dataclass
class HookResult:
    """Outcome of a single hook execution."""

    action: str = "allow"          # "allow" | "deny" | "modify"
    reason: str = ""               # Explanation when deny
    updated_input: dict | None = None   # New params when modify
    additional_context: str = ""   # Extra info appended to LLM context


def aggregate_results(results: list[HookResult]) -> HookResult:
    """Merge multiple hook results into one.

    Rules:
    - Any deny wins over all allow/modify.
    - If no deny, last modify's updated_input is used.
    - additional_context from all hooks is concatenated.
    """
    if not results:
        return HookResult()

    # Collect all additional contexts
    contexts = [r.additional_context for r in results if r.additional_context]

    # Check for any deny
    for r in results:
        if r.action == "deny":
            return HookResult(
                action="deny",
                reason=r.reason,
                additional_context="\n".join(contexts),
            )

    # Check for last modify
    last_modify: HookResult | None = None
    for r in results:
        if r.action == "modify":
            last_modify = r

    if last_modify is not None:
        return HookResult(
            action="modify",
            reason=last_modify.reason,
            updated_input=last_modify.updated_input,
            additional_context="\n".join(contexts),
        )

    # All allow
    return HookResult(
        action="allow",
        additional_context="\n".join(contexts),
    )
