"""Agent ReAct loop: LLM → tool call → result → LLM → ... → done.

Now an AsyncGenerator that yields StreamEvent. Callers consume via:
  async for event in agent_loop(state): ...

For callers that don't need streaming, use run_agent_to_completion(state).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator  # noqa: TC003 — used at runtime for generator return type

from src.agent.compact import (
    auto_compact,
    estimate_tokens,
    get_thresholds,
    micro_compact,
    reactive_compact,
)
from src.agent.messages import format_assistant_msg, format_tool_msg
from src.agent.state import AgentState, ExitReason
from src.llm.adapter import LLMResponse, ToolCallRequest, Usage
from src.project.config import get_settings
from src.streaming.events import StreamEvent

logger = logging.getLogger(__name__)


def _is_context_length_error(exc: Exception) -> bool:
    """Check if an exception is a context length exceeded error."""
    msg = str(exc).lower()
    return "context_length_exceeded" in msg or "prompt_too_long" in msg


async def agent_loop(state: AgentState) -> AsyncIterator[StreamEvent]:
    """Run the ReAct loop, yielding StreamEvent for every delta.

    Sets state.exit_reason before the generator ends.
    """
    model = getattr(state.adapter, "model", "")
    thresholds = get_thresholds(model)
    settings = get_settings()
    keep_recent = settings.compact.micro_keep_recent

    while True:
        # --- compact pre-processing ---
        micro_compact(state.messages, keep_recent=keep_recent)

        tokens = estimate_tokens(state.messages)
        if tokens > thresholds.blocking_limit:
            logger.warning("Token count %d exceeds blocking limit %d", tokens, thresholds.blocking_limit)
            state.exit_reason = ExitReason.TOKEN_LIMIT
            return

        if tokens > thresholds.autocompact_threshold:
            logger.info("Token count %d exceeds autocompact threshold %d, compacting", tokens, thresholds.autocompact_threshold)
            result = await auto_compact(state.messages, state.adapter, model)
            state.messages = result.messages

            if estimate_tokens(state.messages) > thresholds.blocking_limit:
                logger.warning("Still over blocking limit after autocompact")
                state.exit_reason = ExitReason.TOKEN_LIMIT
                return

        # Abort check 1: before LLM call
        if _is_aborted(state):
            state.exit_reason = ExitReason.ABORT
            return

        # Call LLM (streaming)
        try:
            # Accumulate response from stream
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[ToolCallRequest] = []
            usage = Usage()
            finish_reason = "stop"

            async for event in state.adapter.call_stream(
                state.messages,
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
                    state.exit_reason = ExitReason.ERROR
                    return

        except Exception as exc:
            # --- reactive compact ---
            if _is_context_length_error(exc) and not state.has_attempted_reactive_compact:
                logger.info("Context length exceeded, attempting reactive compact")
                result = await reactive_compact(state.messages, state.adapter, model)
                state.messages = result.messages
                state.has_attempted_reactive_compact = True
                continue

            if _is_context_length_error(exc):
                logger.warning("Context length exceeded after reactive compact")
                state.exit_reason = ExitReason.TOKEN_LIMIT
                return

            logger.exception("LLM call failed (non-recoverable)")
            yield StreamEvent(type="error", content=str(exc))
            state.exit_reason = ExitReason.ERROR
            return

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

        # Turn accounting
        state.turn_count += 1
        if state.turn_count >= state.max_turns:
            state.exit_reason = ExitReason.MAX_TURNS
            return


def _is_aborted(state: AgentState) -> bool:
    sig = state.tool_context.abort_signal
    return sig is not None and sig.is_set()


async def run_agent_to_completion(state: AgentState) -> ExitReason:
    """Consume all events from agent_loop, return exit reason.

    Migration helper for callers that don't need streaming
    (spawn_agent, pipeline engine, etc.).
    """
    async for _event in agent_loop(state):
        pass
    return state.exit_reason  # type: ignore[return-value]
