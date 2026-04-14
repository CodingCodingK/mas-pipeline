"""ClawBot factory: wraps create_agent() with post-process patching.

This is the entire mechanism by which clawbot diverges from the generic
agent path:

  1. Call the existing factory with role="clawbot" and let it build the
     normal AgentState (system prompt, tools registry, hooks, MCP, ...).
  2. Append SOUL/USER/TOOLS bootstrap content to state.messages[0]["content"].
  3. If a pending_run exists for this session_key, append the pending block.
  4. Prepend the [Runtime Context] tag block to the LAST user message
     (anti-prompt-injection: untrusted channel/chat_id never reach system).

src/agent/factory.py is unchanged. The only clawbot-aware code outside of
src/clawbot/ is the role==clawbot dispatch in SessionRunner._build_agent_state.
"""

from __future__ import annotations

import asyncio
import logging

from src.agent.factory import create_agent
from src.agent.state import AgentState
from src.clawbot.prompt import build_runtime_context, load_soul_bootstrap
from src.permissions.types import PermissionMode

logger = logging.getLogger(__name__)


async def create_clawbot_agent(
    *,
    task_description: str,
    project_id: int | None,
    run_id: str,
    channel: str,
    chat_id: str,
    permission_mode: PermissionMode,
    abort_signal: asyncio.Event | None = None,
    mcp_manager=None,
) -> AgentState:
    """Build a clawbot AgentState with soul/runtime-context patches applied.

    Signature mirrors the subset of `create_agent` arguments that SessionRunner
    cares about. clawbot-specific positional args (channel/chat_id) are keyword-
    only so future additions don't shift positions.
    """
    state = await create_agent(
        role="clawbot",
        task_description=task_description,
        project_id=project_id,
        run_id=run_id,
        permission_mode=permission_mode,
        abort_signal=abort_signal,
        mcp_manager=mcp_manager,
    )

    # Hard contract check: post-process patching assumes messages[0] is system.
    # build_messages always emits this; the assert exists so a future refactor
    # of context.build_messages can't silently corrupt clawbot prompts.
    if not state.messages or state.messages[0].get("role") != "system":
        raise RuntimeError(
            "create_clawbot_agent: expected state.messages[0] to be a system "
            "message; got %r"
            % (state.messages[0] if state.messages else None)
        )

    # Patch 1: append bootstrap soul content to the system message.
    soul = load_soul_bootstrap()
    if soul:
        state.messages[0]["content"] = (
            f"{state.messages[0]['content']}\n\n---\n\n{soul}"
        )

    # Note: pending_run injection lives in SessionRunner per-turn overlay,
    # not here — it has to refresh every turn as the store changes.

    # Patch 2: prepend runtime context tag to the LAST user message head.
    runtime_ctx = build_runtime_context(channel=channel, chat_id=chat_id)
    if state.messages and state.messages[-1].get("role") == "user":
        last = state.messages[-1]
        original = last.get("content") or ""
        if isinstance(original, str):
            last["content"] = f"{runtime_ctx}\n\n{original}"

    return state
