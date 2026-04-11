"""Unit tests for TelemetryCollector: queueing, batching, drop-oldest,
graceful shutdown, disabled path, pricing calculation.

No PG — the DB session factory is mocked to capture batches in memory.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telemetry.collector import (
    NullTelemetryCollector,
    TelemetryCollector,
    current_project_id,
)
from src.telemetry.pricing import ModelPricing, PricingTable, load_pricing

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


# ── Fake DB session factory ────────────────────────────────


class FakeSession:
    def __init__(self, captured: list[list[dict]]) -> None:
        self.captured = captured
        self._pending: list[dict] = []

    async def execute(self, stmt, rows):  # noqa: ARG002
        if isinstance(rows, list):
            self._pending.extend(rows)
        else:
            self._pending.append(rows)

    async def commit(self) -> None:
        if self._pending:
            self.captured.append(list(self._pending))
            self._pending.clear()

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def make_factory(captured: list[list[dict]]):
    @asynccontextmanager
    async def factory():
        async with FakeSession(captured) as session:
            yield session
    return factory


# ── Tests ──────────────────────────────────────────────────


async def _t_batch_at_size():
    print("\n=== batch_size triggers flush ===")
    captured: list[list[dict]] = []
    collector = TelemetryCollector(
        db_session_factory=make_factory(captured),
        enabled=True,
        batch_size=5,
        flush_interval_sec=60.0,
        max_queue_size=100,
        pricing_table_path="nonexistent.yaml",
    )
    token = current_project_id.set(1)
    try:
        await collector.start()
        for i in range(5):
            collector.record_hook_event(
                hook_type="PreToolUse", decision="allow", latency_ms=i
            )
        # Let the writer loop pick them up.
        await asyncio.sleep(0.1)
        check("batch flushed after hitting size 5",
              len(captured) == 1 and len(captured[0]) == 5)
    finally:
        current_project_id.reset(token)
        await collector.stop(timeout_seconds=3.0)


async def _t_flush_on_interval():
    print("\n=== flush_interval triggers flush ===")
    captured: list[list[dict]] = []
    collector = TelemetryCollector(
        db_session_factory=make_factory(captured),
        enabled=True,
        batch_size=1000,
        flush_interval_sec=0.2,
        max_queue_size=100,
        pricing_table_path="nonexistent.yaml",
    )
    token = current_project_id.set(1)
    try:
        await collector.start()
        for i in range(3):
            collector.record_hook_event(
                hook_type="PreToolUse", decision="allow", latency_ms=i
            )
        await asyncio.sleep(0.5)  # > flush_interval
        check(
            "interval flush fired with partial batch",
            len(captured) >= 1 and sum(len(b) for b in captured) == 3,
        )
    finally:
        current_project_id.reset(token)
        await collector.stop(timeout_seconds=3.0)


async def _t_drop_oldest():
    print("\n=== drop-oldest when queue full ===")
    captured: list[list[dict]] = []
    collector = TelemetryCollector(
        db_session_factory=make_factory(captured),
        enabled=True,
        batch_size=1000,
        flush_interval_sec=60.0,
        max_queue_size=3,
        pricing_table_path="nonexistent.yaml",
    )
    # No start — no writer draining.
    token = current_project_id.set(1)
    try:
        for i in range(10):
            collector.record_hook_event(
                hook_type="PreToolUse", decision="allow", latency_ms=i
            )
        check("queue capped at max_queue_size",
              collector._queue.qsize() == 3)
        check("drop counter tracked", collector._drop_count >= 1)
    finally:
        current_project_id.reset(token)


async def _t_graceful_drain():
    print("\n=== graceful shutdown drain ===")
    captured: list[list[dict]] = []
    collector = TelemetryCollector(
        db_session_factory=make_factory(captured),
        enabled=True,
        batch_size=1000,
        flush_interval_sec=60.0,
        max_queue_size=100,
        pricing_table_path="nonexistent.yaml",
    )
    token = current_project_id.set(1)
    try:
        await collector.start()
        for i in range(7):
            collector.record_hook_event(
                hook_type="PreToolUse", decision="allow", latency_ms=i
            )
        await collector.stop(timeout_seconds=3.0)
        total = sum(len(b) for b in captured)
        check("all 7 events flushed on shutdown", total == 7)
    finally:
        current_project_id.reset(token)


async def _t_disabled_zero_queue():
    print("\n=== disabled collector skips queue ===")
    captured: list[list[dict]] = []
    collector = TelemetryCollector(
        db_session_factory=make_factory(captured),
        enabled=False,
        pricing_table_path="nonexistent.yaml",
    )
    collector.record_hook_event(hook_type="PreToolUse", decision="allow", latency_ms=5)
    collector.record_tool_call(
        tool_name="shell",
        args_preview={"cmd": "ls"},
        duration_ms=10,
        success=True,
    )
    check("disabled queue stays empty", collector._queue.qsize() == 0)
    check("captured stays empty", len(captured) == 0)


async def _t_null_interchangeable():
    print("\n=== NullTelemetryCollector interchangeable ===")
    null = NullTelemetryCollector()
    null.record_llm_call(
        provider="anthropic", model="claude-opus-4-6",
        usage=MagicMock(input_tokens=10, output_tokens=5),
        latency_ms=100, finish_reason="stop",
    )
    null.record_tool_call(
        tool_name="shell", args_preview="ls", duration_ms=5, success=True,
    )
    await null.start()
    await null.stop()
    check("null collector no crash", True)
    check("null queue empty", null._queue.qsize() == 0)


def _t_pricing():
    print("\n=== PricingTable calculation ===")
    table = PricingTable(models={
        "anthropic/claude-opus-4-6": ModelPricing(
            input_usd_per_1k_tokens=0.015,
            output_usd_per_1k_tokens=0.075,
            cache_read_discount_factor=0.1,
        ),
    })
    # Known model: 1000 in + 500 out = 0.015 + 0.0375 = 0.0525
    cost = table.calculate_cost("anthropic", "claude-opus-4-6", 1000, 500)
    check("known-model cost computed", cost is not None and abs(cost - 0.0525) < 1e-9)

    # Unknown model
    cost_unknown = table.calculate_cost("foo", "bar", 1000, 500)
    check("unknown-model cost is None", cost_unknown is None)

    # Cache-read discount: 1000 input tokens, 800 cache-read, 0 output.
    #   billable_input = 200 * 0.015/1000 = 0.003
    #   cache_part     = 800 * 0.015 * 0.1 / 1000 = 0.0012
    #   total          = 0.0042
    cost_cache = table.calculate_cost(
        "anthropic", "claude-opus-4-6", 1000, 0, cache_read_tokens=800
    )
    check("cache-read discount applied",
          cost_cache is not None and abs(cost_cache - 0.0042) < 1e-9)

    # Repeated unknown model should not double-warn (dedup stored in _warned set).
    _ = table.calculate_cost("foo", "bar", 1000, 500)
    check("unknown-model dedup stored", ("foo", "bar") in table._warned)


def _t_load_pricing_missing():
    print("\n=== load_pricing handles missing file ===")
    table = load_pricing("definitely_missing_config.yaml")
    check("load_pricing returns empty on missing file", len(table.models) == 0)


async def _run_all() -> None:
    await _t_batch_at_size()
    await _t_flush_on_interval()
    await _t_drop_oldest()
    await _t_graceful_drain()
    await _t_disabled_zero_queue()
    await _t_null_interchangeable()
    _t_pricing()
    _t_load_pricing_missing()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_run_all())
    print(f"\n{'=' * 50}")
    print(f"Passed: {passed} / {passed + failed}")
    if failed:
        print(f"Failed: {failed}")
        sys.exit(1)
    print("All tests passed.")
