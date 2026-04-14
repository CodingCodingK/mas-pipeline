"""Agent ReAct loop: LLM → tool call → result → LLM → ... → done.

Now an AsyncGenerator that yields StreamEvent. Callers consume via:
  async for event in agent_loop(state): ...

For callers that don't need streaming, use run_agent_to_completion(state).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator  # noqa: TC003 — used at runtime for generator return type
from dataclasses import dataclass

from src.agent.compact import (
    auto_compact,
    estimate_tokens,
    get_thresholds,
    micro_compact,
    reactive_compact,
)
from src.agent.context import slice_messages_for_prompt
from src.agent.messages import format_assistant_msg, format_tool_msg
from src.agent.state import AgentState, ExitReason
from src.llm.adapter import LLMResponse, ToolCallRequest, Usage
from src.project.config import get_settings
from src.streaming.events import StreamEvent
from src.telemetry import get_collector

logger = logging.getLogger(__name__)


def _infer_provider(adapter: object) -> str:
    """Derive the provider label for telemetry.

    Prefers `adapter.provider_label` (set by the router from the resolved
    provider name — e.g. "openai", "deepseek", "qwen") so `llm_call` events
    match the `{provider}/{model}` keys in `config/pricing.yaml`. Falls back
    to the adapter's Python module name for legacy adapters that don't set
    the attribute.
    """
    label = getattr(adapter, "provider_label", None)
    if isinstance(label, str) and label:
        return label
    module = type(adapter).__module__
    return module.rsplit(".", 1)[-1]


def _is_context_length_error(exc: Exception) -> bool:
    """Check if an exception is a context length exceeded error."""
    msg = str(exc).lower()
    return "context_length_exceeded" in msg or "prompt_too_long" in msg


def extract_final_output(messages: list[dict]) -> str:
    """Return the last assistant message's text content.

    Used by run_agent_to_completion and pipeline/_run_node to derive the
    node's final output after the loop exits. Iterates from the tail and
    returns the first assistant message with non-empty string content.
    """
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if content and isinstance(content, str) and content.strip():
                return content.strip()
    return ""


@dataclass
class AgentRunResult:
    """Canonical handoff from run_agent_to_completion to callers.

    Single source of truth for how a completed agent run gets persisted
    — spawn_agent and pipeline._run_node both destructure this instead of
    reaching into state.* fields post-run.
    """

    exit_reason: ExitReason
    messages: list[dict]
    final_output: str
    tool_use_count: int
    cumulative_tokens: int
    duration_ms: int


async def agent_loop(state: AgentState) -> AsyncIterator[StreamEvent]:
    """Run the ReAct loop, yielding StreamEvent for every delta.

    Sets state.exit_reason before the generator ends.
    """
    model = getattr(state.adapter, "model", "")
    thresholds = get_thresholds(model)
    settings = get_settings()
    keep_recent = settings.compact.micro_keep_recent

    collector = get_collector()
    while True:
        # --- compact pre-processing ---
        tokens_pre_micro = estimate_tokens(slice_messages_for_prompt(state.messages))
        micro_started = time.monotonic()
        micro_compact(state.messages, keep_recent=keep_recent)
        tokens_post_micro = estimate_tokens(slice_messages_for_prompt(state.messages))
        if tokens_post_micro < tokens_pre_micro:
            collector.record_compact_event(
                trigger="micro",
                before_tokens=tokens_pre_micro,
                after_tokens=tokens_post_micro,
                duration_ms=int((time.monotonic() - micro_started) * 1000),
                turn_index=state.turn_count,
            )

        # Count only the post-compact-boundary slice. state.messages retains
        # pre-boundary entries for PG audit, but they're invisible to the
        # model and must not be counted against the context budget — otherwise
        # auto_compact would run every turn and grow the list without bound.
        tokens = tokens_post_micro

        if tokens > thresholds.autocompact_threshold and not state.compact_breaker_tripped:
            logger.info(
                "Token count %d exceeds autocompact threshold %d, compacting",
                tokens, thresholds.autocompact_threshold,
            )
            auto_started = time.monotonic()
            try:
                result = await auto_compact(
                    state.messages, state.adapter, model, turn=state.turn_count,
                )
                state.messages = result.messages
                state.consecutive_compact_failures = 0
                collector.record_compact_event(
                    trigger="auto",
                    before_tokens=result.tokens_before,
                    after_tokens=result.tokens_after,
                    duration_ms=int((time.monotonic() - auto_started) * 1000),
                    turn_index=state.turn_count,
                    )
            except Exception:
                state.consecutive_compact_failures += 1
                logger.warning(
                    "auto_compact failed (%d consecutive)",
                    state.consecutive_compact_failures,
                    exc_info=True,
                )
                if state.consecutive_compact_failures >= 3 and not state.compact_breaker_tripped:
                    state.compact_breaker_tripped = True
                    logger.info(
                        "Compact circuit breaker tripped after 3 failures; "
                        "skipping compact for the rest of this runner"
                    )

        # Abort check 1: before LLM call
        if _is_aborted(state):
            state.exit_reason = ExitReason.ABORT
            return

        # Call LLM (streaming)
        provider_name = _infer_provider(state.adapter)
        model_name = getattr(state.adapter, "model", "") or ""
        llm_started_at = time.monotonic()
        try:
            # Accumulate response from stream
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[ToolCallRequest] = []
            usage = Usage()
            finish_reason = "stop"

            async for event in state.adapter.call_stream(
                slice_messages_for_prompt(state.messages),
                state.tools.list_definitions(),
            ):
                if event.type == "text_delta":
                    content_parts.append(event.content)
                    yield event

                elif event.type == "thinking_delta":
                    thinking_parts.append(event.content)
                    yield event

                elif event.type in ("tool_start", "tool_delta"):
                    yield event

                elif event.type == "tool_end":
                    if event.tool_call:
                        tool_calls.append(event.tool_call)
                    yield event

                elif event.type == "usage":
                    if event.usage:
                        usage = event.usage

                elif event.type == "done":
                    finish_reason = event.finish_reason

                elif event.type == "error":
                    yield event
                    collector.record_llm_call(
                        provider=provider_name,
                        model=model_name,
                        usage=usage,
                        latency_ms=int((time.monotonic() - llm_started_at) * 1000),
                        finish_reason="error",
                    )
                    collector.record_error(
                        source="llm", error_type="LLMStreamError",
                        message=event.content or "",
                    )
                    state.exit_reason = ExitReason.ERROR
                    return

        except Exception as exc:
            collector.record_llm_call(
                provider=provider_name,
                model=model_name,
                usage=usage,
                latency_ms=int((time.monotonic() - llm_started_at) * 1000),
                finish_reason="error",
            )
            collector.record_error(source="llm", exc=exc)

            # --- reactive compact ---
            if (
                _is_context_length_error(exc)
                and not state.has_attempted_reactive_compact
                and not state.compact_breaker_tripped
            ):
                logger.info("Context length exceeded, attempting reactive compact")
                reactive_started = time.monotonic()
                try:
                    result = await reactive_compact(
                        state.messages, state.adapter, model, turn=state.turn_count,
                    )
                    state.messages = result.messages
                    state.has_attempted_reactive_compact = True
                    state.consecutive_compact_failures = 0
                    collector.record_compact_event(
                        trigger="reactive",
                        before_tokens=result.tokens_before,
                        after_tokens=result.tokens_after,
                        duration_ms=int((time.monotonic() - reactive_started) * 1000),
                        turn_index=state.turn_count,
                            )
                    continue
                except Exception:
                    state.consecutive_compact_failures += 1
                    logger.warning(
                        "reactive_compact failed (%d consecutive)",
                        state.consecutive_compact_failures,
                        exc_info=True,
                    )
                    if state.consecutive_compact_failures >= 3 and not state.compact_breaker_tripped:
                        state.compact_breaker_tripped = True
                        logger.info(
                            "Compact circuit breaker tripped after 3 failures; "
                            "skipping compact for the rest of this runner"
                        )
                    # Fall through to the unrecoverable error path below.

            if _is_context_length_error(exc):
                logger.warning("Context length exceeded; compact unavailable")
                yield StreamEvent(type="error", content=str(exc))
                state.exit_reason = ExitReason.TOKEN_LIMIT
                return

            logger.exception("LLM call failed (non-recoverable)")
            yield StreamEvent(type="error", content=str(exc))
            state.exit_reason = ExitReason.ERROR
            return

        # Success path — record llm_call telemetry.
        collector.record_llm_call(
            provider=provider_name,
            model=model_name,
            usage=usage,
            latency_ms=int((time.monotonic() - llm_started_at) * 1000),
            finish_reason=finish_reason,
        )

        # Build and append assistant message
        response = LLMResponse(
            content="".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            thinking="".join(thinking_parts) if thinking_parts else None,
        )
        state.messages.append(format_assistant_msg(response))

        # No tool calls → done
        if not tool_calls:
            state.exit_reason = ExitReason.COMPLETED
            return

        # Dispatch tool calls
        results = await state.orchestrator.dispatch(
            tool_calls, state.tool_context
        )

        # Append tool result messages + yield tool_result events
        for tc, tool_result in zip(tool_calls, results, strict=True):
            state.messages.append(format_tool_msg(tc.id, tool_result))
            yield StreamEvent(
                type="tool_result",
                tool_call_id=tc.id,
                output=tool_result.output,
                success=tool_result.success,
            )

        # Abort check 2: after tool execution
        if _is_aborted(state):
            state.exit_reason = ExitReason.ABORT
            return

        # Turn accounting + per-run statistics (add-subagent-data-parity).
        # Usage is normalized across providers — sum the three components.
        state.tool_use_count += len(tool_calls)
        state.cumulative_tokens += (
            (usage.input_tokens or 0)
            + (usage.output_tokens or 0)
            + (usage.thinking_tokens or 0)
        )
        state.turn_count += 1
        if state.turn_count >= state.max_turns:
            state.exit_reason = ExitReason.MAX_TURNS
            return


def _is_aborted(state: AgentState) -> bool:
    sig = state.tool_context.abort_signal
    return sig is not None and sig.is_set()


async def run_agent_to_completion(state: AgentState) -> AgentRunResult:
    """Consume all events from agent_loop, return a full AgentRunResult.

    Callers (spawn_agent, pipeline._run_node) destructure this result and
    pass every field through to complete_agent_run / fail_agent_run so the
    agent_runs row captures the full transcript + statistics.
    """
    started_at = time.monotonic()
    async for _event in agent_loop(state):
        pass
    duration_ms = int((time.monotonic() - started_at) * 1000)
    return AgentRunResult(
        exit_reason=state.exit_reason or ExitReason.ERROR,
        messages=state.messages,
        final_output=extract_final_output(state.messages),
        tool_use_count=state.tool_use_count,
        cumulative_tokens=state.cumulative_tokens,
        duration_ms=duration_ms,
    )
