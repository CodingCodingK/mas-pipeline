"""Compact: token estimation, threshold calculation, micro/auto/reactive compaction.

Aligns with Claude Code's compact design (src/services/compact/*):

- Compact is APPEND-ONLY: auto_compact / reactive_compact never shrink the
  input list. They append two new tail entries (a summary message + a
  boundary marker) so that `_pg_synced_count`-style monotonic counters stay
  correct and PG retains the full audit log.
- The summarizer call uses the main agent's adapter + model (not a cheap
  tier). On prompt-too-long errors we drop the oldest half of the older
  blob and retry once, mirroring CC's `truncateHeadForPTLRetry`.
- Pre-compact messages remain in the returned list; `build_messages`
  filters them out at prompt-assembly time by scanning for the boundary
  marker flag (`metadata.is_compact_boundary`).
"""

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

# Max prompt-too-long retries inside a single compact call. CC uses the same
# "drop oldest half, retry once" shape in truncateHeadForPTLRetry.
_MAX_SUMMARIZER_RETRIES = 1


@dataclass
class CompactThresholds:
    context_window: int
    autocompact_threshold: int
    blocking_limit: int


@dataclass
class CompactResult:
    """Result of an append-only compact pass.

    - `messages`: the original input list with two new entries appended to
      the tail: a summary message (`metadata.is_compact_summary=True`) and
      a boundary marker (`metadata.is_compact_boundary=True`). When compact
      is a no-op (not enough older messages), `messages` is the input list
      unchanged and `summary` is empty.
    - `summary`: the LLM-generated summary text.
    - `tokens_before`: token estimate of the full input list.
    - `tokens_after`: token estimate of the POST-BOUNDARY slice (what the
      next turn will actually feed to the model), not the whole list.
    """

    messages: list[dict]
    summary: str
    tokens_before: int
    tokens_after: int


# ── Token estimation ────────────────────────────────────────


def estimate_tokens(messages: list[dict]) -> int:
    """Estimate token count using character-based approximation (len/4).

    Matches CC's `roughTokenCountEstimation` (tokenEstimation.ts:203). The
    same bytes-per-token constant is used for both ASCII and CJK content —
    CJK under-counts by ~3x but in a conservative (late-compact) direction,
    and the reactive path catches the true overflow anyway.
    """
    if not messages:
        return 0
    total_chars = sum(len(json.dumps(msg, ensure_ascii=False)) for msg in messages)
    return total_chars // 4


# ── Context window resolution ───────────────────────────────


def get_context_window(model: str) -> int:
    """Get context window for model: settings > built-in defaults > 128K fallback."""
    settings = get_settings()
    configured = settings.context_windows.get(model)
    if configured is not None:
        return configured
    builtin = _DEFAULT_CONTEXT_WINDOWS.get(model)
    if builtin is not None:
        return builtin
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


def micro_compact(messages: list[dict], keep_recent: int = 5) -> list[dict]:
    """Clear old tool-result content, keeping recent ones intact.

    Two protection layers (aligned with Claude Code's micro-compact design):
    1. **Current-turn shield**: all tool results after the last assistant
       message are unconditionally preserved — the LLM that issued those
       tool calls has never seen the results yet; clearing them would cause
       information loss or redundant re-calls.
    2. **keep_recent budget**: among the *older* tool results (before the
       last assistant message), keep the N most recent intact; clear the rest.

    Modifies messages in-place and returns the same list.
    """
    # Find the last assistant message index — everything after it belongs
    # to the current turn and must not be touched.
    last_assistant_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_assistant_idx = i
            break

    # Collect tool-result indices that are BEFORE the last assistant msg
    # (i.e. from completed prior turns only).
    older_tool_indices = [
        i for i, msg in enumerate(messages)
        if msg.get("role") == "tool" and i < last_assistant_idx
    ]

    if len(older_tool_indices) <= keep_recent:
        return messages

    to_clear = older_tool_indices[: len(older_tool_indices) - keep_recent]
    for idx in to_clear:
        if messages[idx].get("content") != "[Old tool result cleared]":
            messages[idx] = {**messages[idx], "content": "[Old tool result cleared]"}

    return messages


# ── Auto / reactive compact ─────────────────────────────────

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
    *,
    turn: int = 0,
) -> CompactResult:
    """Generate a summary of older messages, append summary + boundary to the tail.

    Keeps ~30% of context_window worth of messages after the boundary.
    The pre-boundary messages remain in the returned list untouched.
    """
    return await _compact(
        messages,
        adapter,
        model,
        recent_budget_pct=0.30,
        turn=turn,
        label="Autocompact",
    )


async def reactive_compact(
    messages: list[dict],
    adapter: LLMAdapter,
    model: str,
    *,
    turn: int = 0,
) -> CompactResult:
    """Emergency compact on context_length_exceeded.

    More aggressive than auto_compact: keeps only ~20% of context_window
    worth of messages after the boundary. Same append-only semantics.
    """
    return await _compact(
        messages,
        adapter,
        model,
        recent_budget_pct=0.20,
        turn=turn,
        label="Reactive compact",
    )


async def _compact(
    messages: list[dict],
    adapter: LLMAdapter,
    model: str,
    *,
    recent_budget_pct: float,
    turn: int,
    label: str,
) -> CompactResult:
    tokens_before = estimate_tokens(messages)
    ctx_window = get_context_window(model)

    # Compact operates on the post-latest-boundary slice only. Earlier
    # boundaries and their pre-boundary audit entries are invisible to the
    # model and must not be re-summarized. This makes cascading compacts
    # compose correctly: each new summary subsumes the previous one because
    # the previous summary lives at the head of the current visible slice.
    slice_start = _latest_boundary_end(messages)
    visible = messages[slice_start:]

    recent_budget = int(ctx_window * recent_budget_pct)
    split_idx_in_visible = _find_split_point(visible, recent_budget)

    if split_idx_in_visible <= 1:
        return CompactResult(
            messages=messages,
            summary="",
            tokens_before=tokens_before,
            tokens_after=tokens_before,
        )

    older = visible[:split_idx_in_visible]

    # Summarize with retry-on-overflow. Drops oldest half of the older blob
    # on prompt-too-long errors, retries once, then re-raises.
    summary = await _summarize_with_retry(older, adapter, model)

    summary_msg = {
        "role": "user",
        "content": summary,
        "metadata": {"is_compact_summary": True},
    }
    boundary_msg = {
        "role": "system",
        "content": "",
        "metadata": {"is_compact_boundary": True, "turn": turn},
    }

    new_messages = messages + [summary_msg, boundary_msg]

    # tokens_after reflects what the NEXT turn will see: summary + post-boundary
    # slice. Since we just appended the boundary at the very tail, the
    # post-boundary slice is empty — the effective prompt size is the summary
    # message alone plus whatever new user input the caller adds on top.
    tokens_after = estimate_tokens([summary_msg])

    logger.info(
        "%s: %d -> %d tokens (visible slice split at %d, kept %d recent pre-append)",
        label, tokens_before, tokens_after, split_idx_in_visible,
        len(visible) - split_idx_in_visible,
    )

    return CompactResult(
        messages=new_messages,
        summary=summary,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
    )


async def _summarize_with_retry(
    older: list[dict],
    adapter: LLMAdapter,
    model: str,
) -> str:
    """Call the summarizer with head-drop retry on prompt-too-long errors.

    Mirrors CC's truncateHeadForPTLRetry: if the initial call fails with a
    context/prompt-too-long error, drop the oldest 50% of `older` and retry
    once. On second failure, re-raise — the caller (SessionRunner) will
    count it against the circuit breaker.
    """
    attempt_blob = older
    last_exc: Exception | None = None

    for attempt in range(_MAX_SUMMARIZER_RETRIES + 1):
        summary_messages = [
            {"role": "system", "content": _SUMMARY_PROMPT},
            {"role": "user", "content": _format_for_summary(attempt_blob)},
        ]
        try:
            response = await adapter.call(summary_messages, tools=[])
            return response.content or ""
        except Exception as exc:
            last_exc = exc
            if not _is_context_length_error(exc):
                raise
            # Head-drop and retry once.
            if attempt < _MAX_SUMMARIZER_RETRIES and len(attempt_blob) > 2:
                drop_n = len(attempt_blob) // 2
                attempt_blob = attempt_blob[drop_n:]
                logger.warning(
                    "Summarizer prompt-too-long; dropped oldest %d messages, retrying",
                    drop_n,
                )
                continue
            raise

    # Unreachable — loop either returns or raises.
    raise last_exc  # type: ignore[misc]


def _is_context_length_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "context_length_exceeded" in msg
        or "prompt_too_long" in msg
        or "context length" in msg
        or "too long" in msg
        or "exceed" in msg and "context" in msg
    )


# ── Helpers ─────────────────────────────────────────────────


def _latest_boundary_end(messages: list[dict]) -> int:
    """Return the index of the first message AFTER the latest compact boundary.

    Returns 0 if no boundary is present (all messages are visible).
    """
    for i in range(len(messages) - 1, -1, -1):
        meta = messages[i].get("metadata") or {}
        if meta.get("is_compact_boundary"):
            return i + 1
    return 0


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
            lines.append(f"[tool result {tc_id}]: {str(content)[:500]}")
        elif role == "assistant" and msg.get("tool_calls"):
            calls = msg["tool_calls"]
            call_strs = ", ".join(tc.get("function", {}).get("name", "?") for tc in calls)
            lines.append(f"[assistant calls: {call_strs}]")
            if content:
                lines.append(f"[assistant]: {content}")
        else:
            lines.append(f"[{role}]: {str(content)[:2000]}")
    return "\n".join(lines)
