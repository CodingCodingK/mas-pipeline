"""Agent ReAct loop: LLM → tool call → result → LLM → ... → done."""

from __future__ import annotations

import logging

from src.agent.compact import (
    auto_compact,
    estimate_tokens,
    get_thresholds,
    micro_compact,
    reactive_compact,
)
from src.agent.messages import format_assistant_msg, format_tool_msg
from src.agent.state import AgentState, ExitReason
from src.project.config import get_settings

logger = logging.getLogger(__name__)


def _is_context_length_error(exc: Exception) -> bool:
    """Check if an exception is a context length exceeded error."""
    msg = str(exc).lower()
    return "context_length_exceeded" in msg or "prompt_too_long" in msg


async def agent_loop(state: AgentState) -> ExitReason:
    """Run the ReAct loop until completion or exit condition.

    All dependencies (adapter, tools, orchestrator, tool_context) live on *state*.
    Returns an ExitReason; callers can inspect state.turn_count, state.messages, etc.
    """
    # Resolve model name for thresholds
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
            return ExitReason.TOKEN_LIMIT

        if tokens > thresholds.autocompact_threshold:
            logger.info("Token count %d exceeds autocompact threshold %d, compacting", tokens, thresholds.autocompact_threshold)
            result = await auto_compact(state.messages, state.adapter, model)
            state.messages = result.messages

            if estimate_tokens(state.messages) > thresholds.blocking_limit:
                logger.warning("Still over blocking limit after autocompact")
                return ExitReason.TOKEN_LIMIT

        # Abort check 1: before LLM call
        if _is_aborted(state):
            return ExitReason.ABORT

        # Call LLM
        try:
            response = await state.adapter.call(
                state.messages,
                state.tools.list_definitions(),
            )
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
                return ExitReason.TOKEN_LIMIT

            logger.exception("LLM call failed (non-recoverable)")
            return ExitReason.ERROR

        # Append assistant message
        state.messages.append(format_assistant_msg(response))

        # No tool calls → done
        if not response.tool_calls:
            return ExitReason.COMPLETED

        # Dispatch tool calls
        results = await state.orchestrator.dispatch(
            response.tool_calls, state.tool_context
        )

        # Append tool result messages
        for tc, result in zip(response.tool_calls, results, strict=True):
            state.messages.append(format_tool_msg(tc.id, result))

        # Abort check 2: after tool execution
        if _is_aborted(state):
            return ExitReason.ABORT

        # Turn accounting
        state.turn_count += 1
        if state.turn_count >= state.max_turns:
            return ExitReason.MAX_TURNS


def _is_aborted(state: AgentState) -> bool:
    sig = state.tool_context.abort_signal
    return sig is not None and sig.is_set()
