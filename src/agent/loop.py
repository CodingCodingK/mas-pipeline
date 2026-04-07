"""Agent ReAct loop: LLM → tool call → result → LLM → ... → done."""

from __future__ import annotations

import logging

from src.agent.messages import format_assistant_msg, format_tool_msg
from src.agent.state import AgentState, ExitReason

logger = logging.getLogger(__name__)


async def agent_loop(state: AgentState) -> ExitReason:
    """Run the ReAct loop until completion or exit condition.

    All dependencies (adapter, tools, orchestrator, tool_context) live on *state*.
    Returns an ExitReason; callers can inspect state.turn_count, state.messages, etc.
    """
    while True:
        # --- compact pre-processing (Phase 3) ---
        # microcompact: clear old tool results
        # autocompact: compress when token count exceeds threshold
        # blocking_limit: return TOKEN_LIMIT if still over limit after compact

        # Abort check 1: before LLM call
        if _is_aborted(state):
            return ExitReason.ABORT

        # Call LLM
        try:
            response = await state.adapter.call(
                state.messages,
                state.tools.list_definitions(),
            )
        except Exception:
            logger.exception("LLM call failed (non-recoverable)")
            return ExitReason.ERROR

        # --- reactive compact (Phase 3) ---
        # If LLM returns prompt_too_long and not has_attempted_reactive_compact:
        #   compact once, set flag, continue
        # Else: return TOKEN_LIMIT

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
