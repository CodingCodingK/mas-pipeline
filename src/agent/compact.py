"""Compact: token estimation, threshold calculation, micro/auto/reactive compaction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.project.config import get_settings

if TYPE_CHECKING:
    from src.llm.adapter import LLMAdapter

logger = logging.getLogger(__name__)

# Built-in context window defaults for common models.
_DEFAULT_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-6": 200000,
    "claude-haiku-4-5": 200000,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
}
DEFAULT_CONTEXT_WINDOW = 128000


@dataclass
class CompactThresholds:
    context_window: int
    autocompact_threshold: int
    blocking_limit: int


@dataclass
class CompactResult:
    messages: list[dict]
    summary: str
    tokens_before: int
    tokens_after: int


# ── Token estimation ────────────────────────────────────────


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate token count using character-based approximation (len/4)."""
    if not messages:
        return 0
    total_chars = sum(len(json.dumps(msg, ensure_ascii=False)) for msg in messages)
    return total_chars // 4


# ── Context window resolution ───────────────────────────────


def get_context_window(model: str) -> int:
    """Get context window for model: settings > built-in defaults > 128K fallback."""
    settings = get_settings()
    # Priority 1: user config
    configured = settings.context_windows.get(model)
    if configured is not None:
        return configured
    # Priority 2: built-in defaults
    builtin = _DEFAULT_CONTEXT_WINDOWS.get(model)
    if builtin is not None:
        return builtin
    # Priority 3: fallback
    return DEFAULT_CONTEXT_WINDOW


# ── Threshold calculation ───────────────────────────────────


def get_thresholds(model: str) -> CompactThresholds:
    """Compute compact thresholds from model context window and percentage settings."""
    settings = get_settings()
    ctx_window = get_context_window(model)
    return CompactThresholds(
        context_window=ctx_window,
        autocompact_threshold=int(ctx_window * settings.compact.autocompact_pct),
        blocking_limit=int(ctx_window * settings.compact.blocking_pct),
    )


# ── Microcompact ────────────────────────────────────────────


def micro_compact(messages: list[dict], keep_recent: int = 3) -> list[dict]:
    """Clear old tool-result content, keeping only the most recent ones intact.

    Modifies messages in-place and returns the same list.
    """
    tool_indices = [i for i, msg in enumerate(messages) if msg.get("role") == "tool"]

    if len(tool_indices) <= keep_recent:
        return messages

    to_clear = tool_indices[: len(tool_indices) - keep_recent]
    for idx in to_clear:
        if messages[idx].get("content") != "[Old tool result cleared]":
            messages[idx] = {**messages[idx], "content": "[Old tool result cleared]"}

    return messages


# ── Autocompact ─────────────────────────────────────────────

_SUMMARY_PROMPT = """\
Summarize the conversation so far. This summary will replace the older messages \
to free up context space. The conversation will continue after this summary.

IMPORTANT: Preserve the following in your summary:
- Key decisions and conclusions made
- File paths and code snippets that were discussed
- Error messages and their fixes
- Task progress and current status
- User preferences and instructions
- Any pending work or open questions

Format as a structured summary with clear sections. Be concise but complete.
Do NOT omit technical details (paths, function names, error messages) as they \
are needed for the conversation to continue effectively.
"""


async def auto_compact(
    messages: list[dict],
    adapter: LLMAdapter,
    model: str,
) -> CompactResult:
    """Compress older messages into a summary, keeping recent messages intact.

    Keeps ~30% of context_window worth of recent messages.
    """
    from src.llm.router import route

    tokens_before = estimate_tokens(messages)
    ctx_window = get_context_window(model)

    # Keep recent messages that fit in 30% of context
    recent_budget = int(ctx_window * 0.30)
    split_idx = _find_split_point(messages, recent_budget)

    if split_idx <= 1:
        return CompactResult(
            messages=messages,
            summary="",
            tokens_before=tokens_before,
            tokens_after=tokens_before,
        )

    older = messages[:split_idx]
    recent = messages[split_idx:]

    # Generate summary using light-tier model
    light = route("light")
    summary_messages = [
        {"role": "system", "content": _SUMMARY_PROMPT},
        {"role": "user", "content": _format_for_summary(older)},
    ]
    response = await light.call(summary_messages, tools=[])
    summary = response.content or ""

    summary_msg = {
        "role": "user",
        "content": f"[CONVERSATION SUMMARY]\n{summary}",
    }
    new_messages = [summary_msg] + recent

    await _save_summary(summary, estimate_tokens([summary_msg]))

    tokens_after = estimate_tokens(new_messages)
    logger.info(
        "Autocompact: %d -> %d tokens (split at %d, kept %d recent)",
        tokens_before, tokens_after, split_idx, len(recent),
    )

    return CompactResult(
        messages=new_messages,
        summary=summary,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )


# ── Reactive compact ───────────────────────────────────────


async def reactive_compact(
    messages: list[dict],
    adapter: LLMAdapter,
    model: str,
) -> CompactResult:
    """Emergency compact: keeps only 20% of context_window worth of recent messages."""
    from src.llm.router import route

    tokens_before = estimate_tokens(messages)
    ctx_window = get_context_window(model)

    recent_budget = int(ctx_window * 0.20)
    split_idx = _find_split_point(messages, recent_budget)

    if split_idx <= 1:
        return CompactResult(
            messages=messages,
            summary="",
            tokens_before=tokens_before,
            tokens_after=tokens_before,
        )

    older = messages[:split_idx]
    recent = messages[split_idx:]

    light = route("light")
    summary_messages = [
        {"role": "system", "content": _SUMMARY_PROMPT},
        {"role": "user", "content": _format_for_summary(older)},
    ]
    response = await light.call(summary_messages, tools=[])
    summary = response.content or ""

    summary_msg = {
        "role": "user",
        "content": f"[CONVERSATION SUMMARY]\n{summary}",
    }
    new_messages = [summary_msg] + recent

    await _save_summary(summary, estimate_tokens([summary_msg]))

    tokens_after = estimate_tokens(new_messages)
    logger.info(
        "Reactive compact: %d -> %d tokens (split at %d, kept %d recent)",
        tokens_before, tokens_after, split_idx, len(recent),
    )

    return CompactResult(
        messages=new_messages,
        summary=summary,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )


# ── Helpers ─────────────────────────────────────────────────


def _find_split_point(messages: list[dict], recent_token_budget: int) -> int:
    """Find index to split messages, keeping recent messages within budget.

    Returns the index where older messages end (exclusive).
    """
    cumulative = 0
    for i in range(len(messages) - 1, -1, -1):
        tokens = estimate_tokens([messages[i]])
        cumulative += tokens
        if cumulative > recent_token_budget:
            return i + 1
    return 0


def _format_for_summary(messages: list[dict]) -> str:
    """Format messages into a readable text for the summary LLM."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "tool":
            tc_id = msg.get("tool_call_id", "?")
            lines.append(f"[tool result {tc_id}]: {content[:500]}")
        elif role == "assistant" and msg.get("tool_calls"):
            calls = msg["tool_calls"]
            call_strs = ", ".join(tc.get("function", {}).get("name", "?") for tc in calls)
            lines.append(f"[assistant calls: {call_strs}]")
            if content:
                lines.append(f"[assistant]: {content}")
        else:
            lines.append(f"[{role}]: {content[:2000]}")
    return "\n".join(lines)


async def _save_summary(summary: str, token_count: int) -> None:
    """Persist compact summary to PG. Best-effort, does not raise on failure."""
    try:
        from src.db import get_db
        from src.models import CompactSummary

        async with get_db() as session:
            record = CompactSummary(
                session_id="",
                summary=summary,
                token_count=token_count,
            )
            session.add(record)
            await session.commit()
    except Exception:
        logger.warning("Failed to save compact summary", exc_info=True)
