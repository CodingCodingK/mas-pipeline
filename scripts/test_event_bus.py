"""Unit tests for EventBus: subscribe/emit fan-out, overflow drop-oldest,
rate-limited warnings, close semantics, no background tasks.

No PG, no mocks — pure in-process queue behavior.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.events.bus import EventBus

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


# ── Tests ──────────────────────────────────────────────────


async def _t_fanout_two_subscribers():
    print("\n=== fan-out to two subscribers ===")
    bus = EventBus()
    q1 = bus.subscribe("a")
    q2 = bus.subscribe("b")
    bus.emit({"id": 1})
    bus.emit({"id": 2})
    check("q1 received 2 events", q1.qsize() == 2)
    check("q2 received 2 events", q2.qsize() == 2)
    e1 = await q1.get()
    e2 = await q2.get()
    check("q1 first event matches", e1 == {"id": 1})
    check("q2 first event matches", e2 == {"id": 1})


async def _t_distinct_queues():
    print("\n=== subscribe returns distinct queues ===")
    bus = EventBus()
    q1 = bus.subscribe("a")
    q2 = bus.subscribe("a")  # same name, still independent
    check("distinct queue objects", q1 is not q2)
    bus.emit("x")
    check("q1 got it", q1.qsize() == 1)
    check("q2 got it too (independent)", q2.qsize() == 1)


async def _t_custom_max_size():
    print("\n=== custom max_size per subscriber ===")
    bus = EventBus(queue_size=100)
    q_small = bus.subscribe("small", max_size=2)
    q_big = bus.subscribe("big")
    check("small queue maxsize is 2", q_small.maxsize == 2)
    check("big queue uses default 100", q_big.maxsize == 100)


async def _t_zero_subscribers_noop():
    print("\n=== emit with zero subscribers is no-op ===")
    bus = EventBus()
    # Should not raise.
    bus.emit("lonely")
    check("emit with no subscribers did not raise", True)


async def _t_emit_is_synchronous():
    print("\n=== emit is synchronous (no await needed) ===")
    bus = EventBus()
    q = bus.subscribe("s")
    # Plain call, no await — must complete immediately.
    result = bus.emit("sync-event")
    check("emit returns None synchronously", result is None)
    check("event is already in queue", q.qsize() == 1)


async def _t_drop_oldest():
    print("\n=== drop-oldest when queue is full ===")
    bus = EventBus()
    q = bus.subscribe("s", max_size=3)
    for i in range(5):
        bus.emit(i)
    # Queue should hold exactly 3 events: the last 3 emitted (2, 3, 4).
    check("queue size is 3", q.qsize() == 3)
    drained = []
    while not q.empty():
        drained.append(await q.get())
    check("dropped oldest, kept newest", drained == [2, 3, 4])


async def _t_full_subscriber_does_not_affect_others():
    print("\n=== one full subscriber does not affect others ===")
    bus = EventBus()
    q_slow = bus.subscribe("slow", max_size=2)
    q_fast = bus.subscribe("fast", max_size=1000)
    for i in range(10):
        bus.emit(i)
    check("slow dropped down to maxsize 2", q_slow.qsize() == 2)
    check("fast received all 10", q_fast.qsize() == 10)


async def _t_warning_rate_limited(caplog_handler):
    print("\n=== warning is rate-limited ===")
    bus = EventBus()
    bus.subscribe("s", max_size=1)
    caplog_handler.records.clear()
    for _ in range(100):
        bus.emit("spam")
    warnings = [
        r for r in caplog_handler.records
        if r.levelno == logging.WARNING and "event_bus" in r.getMessage()
    ]
    check("at most 1 warning emitted in the burst", len(warnings) <= 1)


async def _t_close_makes_emit_noop():
    print("\n=== close makes emit a no-op but preserves pre-close events ===")
    bus = EventBus()
    q = bus.subscribe("s")
    bus.emit("before-close")
    bus.close()
    bus.emit("after-close")
    check("pre-close event still in queue", q.qsize() == 1)
    drained = await q.get()
    check("drained is the pre-close event", drained == "before-close")


async def _t_bus_owns_no_task():
    print("\n=== bus construction does not schedule any asyncio.Task ===")
    before = {t for t in asyncio.all_tasks()}
    bus = EventBus()
    bus.subscribe("a")
    bus.subscribe("b")
    bus.emit("x")
    after = {t for t in asyncio.all_tasks()}
    check("no new task scheduled by bus", after == before)


# ── Runner ─────────────────────────────────────────────────


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


async def main() -> int:
    handler = _ListHandler()
    logger = logging.getLogger("src.events.bus")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    await _t_fanout_two_subscribers()
    await _t_distinct_queues()
    await _t_custom_max_size()
    await _t_zero_subscribers_noop()
    await _t_emit_is_synchronous()
    await _t_drop_oldest()
    await _t_full_subscriber_does_not_affect_others()
    await _t_warning_rate_limited(handler)
    await _t_close_makes_emit_noop()
    await _t_bus_owns_no_task()

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main()))
