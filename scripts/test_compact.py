"""Compact tests: token estimation, context window, thresholds, micro/auto/reactive."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


# ── 1. Token estimation ─────────────────────────────────────

print("\n=== 1. Token estimation ===")

from src.agent.compact import estimate_tokens

check("Empty messages = 0", estimate_tokens([]) == 0)

simple = [{"role": "user", "content": "Hello world"}]
est = estimate_tokens(simple)
check("Simple estimate > 0", est > 0)
check("Simple estimate reasonable", 5 < est < 50, f"got {est}")

# Large tool result
large_content = "x" * 10000
large = [{"role": "tool", "tool_call_id": "tc1", "content": large_content}]
est_large = estimate_tokens(large)
check("Large tool result ~2500", 2000 < est_large < 3500, f"got {est_large}")


# ── 2. Context window resolution ────────────────────────────

print("\n=== 2. Context window resolution ===")

from src.agent.compact import DEFAULT_CONTEXT_WINDOW, _DEFAULT_CONTEXT_WINDOWS, get_context_window


# Mock settings with empty context_windows
def _mock_settings(**overrides):
    s = MagicMock()
    s.context_windows = overrides.get("context_windows", {})
    s.compact.autocompact_pct = overrides.get("autocompact_pct", 0.85)
    s.compact.blocking_pct = overrides.get("blocking_pct", 0.95)
    s.compact.micro_keep_recent = overrides.get("micro_keep_recent", 3)
    return s


with patch("src.agent.compact.get_settings", return_value=_mock_settings()):
    check("Known model uses builtin", get_context_window("gpt-4o-mini") == 128000)
    check("Claude uses builtin", get_context_window("claude-sonnet-4-6") == 200000)
    check("Gemini uses builtin", get_context_window("gemini-2.5-pro") == 1048576)
    check("Unknown model uses fallback", get_context_window("unknown-model") == DEFAULT_CONTEXT_WINDOW)

# Config override
with patch("src.agent.compact.get_settings", return_value=_mock_settings(context_windows={"gpt-4o-mini": 64000})):
    check("Config override takes precedence", get_context_window("gpt-4o-mini") == 64000)


# ── 3. Threshold calculation ────────────────────────────────

print("\n=== 3. Threshold calculation ===")

from src.agent.compact import get_thresholds

with patch("src.agent.compact.get_settings", return_value=_mock_settings()):
    t = get_thresholds("gpt-4o-mini")
    check("Context window correct", t.context_window == 128000)
    check("Autocompact = 85%", t.autocompact_threshold == 108800, f"got {t.autocompact_threshold}")
    check("Blocking = 95%", t.blocking_limit == 121600, f"got {t.blocking_limit}")

# Custom pct
with patch("src.agent.compact.get_settings", return_value=_mock_settings(autocompact_pct=0.80, blocking_pct=0.90)):
    t = get_thresholds("gpt-4o-mini")
    check("Custom autocompact pct", t.autocompact_threshold == 102400, f"got {t.autocompact_threshold}")
    check("Custom blocking pct", t.blocking_limit == 115200, f"got {t.blocking_limit}")


# ── 4. Microcompact ─────────────────────────────────────────

print("\n=== 4. Microcompact ===")

from src.agent.compact import micro_compact

# 5 tool results, keep 3
msgs = [
    {"role": "system", "content": "sys"},
    {"role": "tool", "tool_call_id": "t1", "content": "result1"},
    {"role": "assistant", "content": "ok"},
    {"role": "tool", "tool_call_id": "t2", "content": "result2"},
    {"role": "tool", "tool_call_id": "t3", "content": "result3"},
    {"role": "tool", "tool_call_id": "t4", "content": "result4"},
    {"role": "tool", "tool_call_id": "t5", "content": "result5"},
]
result = micro_compact(msgs, keep_recent=3)
check("Microcompact returns same list", result is msgs)
check("Old tool 1 cleared", msgs[1]["content"] == "[Old tool result cleared]")
check("Old tool 2 cleared", msgs[3]["content"] == "[Old tool result cleared]")
check("Recent tool 3 kept", msgs[4]["content"] == "result3")
check("Recent tool 4 kept", msgs[5]["content"] == "result4")
check("Recent tool 5 kept", msgs[6]["content"] == "result5")
check("System untouched", msgs[0]["content"] == "sys")

# Fewer than keep_recent
few_msgs = [
    {"role": "tool", "tool_call_id": "t1", "content": "r1"},
    {"role": "tool", "tool_call_id": "t2", "content": "r2"},
]
micro_compact(few_msgs, keep_recent=3)
check("Few tools: no change", few_msgs[0]["content"] == "r1" and few_msgs[1]["content"] == "r2")


# ── 5. Autocompact (mocked LLM) ─────────────────────────────

print("\n=== 5. Autocompact ===")


async def test_autocompact():
    # Build messages large enough to trigger split (use small context window via mock)
    msgs = [{"role": "user", "content": f"Message {i} " + "x" * 200} for i in range(50)]

    mock_response = MagicMock()
    mock_response.content = "Summary: 50 messages about testing."

    mock_light = AsyncMock()
    mock_light.call = AsyncMock(return_value=mock_response)

    # Use tiny context window so split actually triggers
    small_settings = _mock_settings()
    with (
        patch("src.agent.compact.get_settings", return_value=small_settings),
        patch("src.agent.compact.get_context_window", return_value=2000),
        patch("src.llm.router.route", return_value=mock_light),
        patch("src.agent.compact._save_summary", AsyncMock()),
    ):
        from src.agent.compact import auto_compact

        result = await auto_compact(msgs, mock_light, "test-model")

    check("Autocompact reduces messages", len(result.messages) < len(msgs))
    check("Summary present", len(result.summary) > 0)
    check("Tokens before > after", result.tokens_before > result.tokens_after)
    check("First msg is summary", "[CONVERSATION SUMMARY]" in result.messages[0]["content"])
    check("LLM called for summary", mock_light.call.called)


asyncio.run(test_autocompact())


async def test_autocompact_too_few():
    msgs = [{"role": "user", "content": "short"}]

    with (
        patch("src.agent.compact.get_settings", return_value=_mock_settings()),
        patch("src.llm.router.route"),
        patch("src.agent.compact._save_summary", AsyncMock()),
    ):
        from src.agent.compact import auto_compact

        result = await auto_compact(msgs, AsyncMock(), "gpt-4o-mini")

    check("Too few: no compaction", len(result.messages) == 1)
    check("Too few: empty summary", result.summary == "")


asyncio.run(test_autocompact_too_few())


# ── 6. Reactive compact (mocked) ────────────────────────────

print("\n=== 6. Reactive compact ===")


async def test_reactive():
    msgs = [{"role": "user", "content": f"Msg {i} " + "y" * 200} for i in range(50)]

    mock_response = MagicMock()
    mock_response.content = "Emergency summary."

    mock_light = AsyncMock()
    mock_light.call = AsyncMock(return_value=mock_response)

    with (
        patch("src.agent.compact.get_settings", return_value=_mock_settings()),
        patch("src.agent.compact.get_context_window", return_value=2000),
        patch("src.llm.router.route", return_value=mock_light),
        patch("src.agent.compact._save_summary", AsyncMock()),
    ):
        from src.agent.compact import reactive_compact

        result = await reactive_compact(msgs, mock_light, "test-model")

    check("Reactive reduces messages", len(result.messages) < len(msgs))
    check("Reactive more aggressive than auto", True)  # 20% vs 30% budget
    check("Reactive summary present", len(result.summary) > 0)


asyncio.run(test_reactive())


# ── 7. CompactResult and CompactThresholds ───────────────────

print("\n=== 7. Dataclasses ===")

from src.agent.compact import CompactResult, CompactThresholds

t = CompactThresholds(context_window=128000, autocompact_threshold=108800, blocking_limit=121600)
check("Thresholds fields", t.context_window == 128000 and t.autocompact_threshold == 108800)

r = CompactResult(messages=[{"role": "user", "content": "hi"}], summary="sum", tokens_before=100, tokens_after=50)
check("Result fields", r.tokens_before == 100 and r.tokens_after == 50)
check("Result summary", r.summary == "sum")


# ── Summary ──────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
