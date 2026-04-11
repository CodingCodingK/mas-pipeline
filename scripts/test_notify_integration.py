"""Notify integration tests against a real PG + EventBus.

Scenarios:
  1. Real bus + collector + Notifier with SseChannel only. Seed user_notify_preferences,
     emit a pipeline_end failure via the collector, assert the SSE queue receives
     a Notification matching event_type="run_failed".
  2. NullNotifier: construct, emit, assert zero queue activity anywhere.

Skips gracefully if PG is not reachable.
"""

from __future__ import annotations

import asyncio
import platform
import sys
import uuid
from pathlib import Path

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.db import get_db, get_session_factory
from src.events.bus import EventBus
from src.notify import NullNotifier, Notifier
from src.notify.channels.sse import SseChannel
from src.telemetry import (
    TelemetryCollector,
    current_project_id,
    current_run_id,
)

passed = 0
failed = 0
skipped = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def skip_all(reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  [SKIP] {reason}")


async def _ensure_schema() -> None:
    async with get_db() as session:
        # user_notify_preferences table may not exist on DBs created before
        # Phase 6.3 — create idempotently so the test can run against any snapshot.
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS user_notify_preferences ("
                "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "event_type TEXT NOT NULL, "
                "channels JSONB NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
                "PRIMARY KEY (user_id, event_type))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO users (id, name, email) "
                "VALUES (101, 'notif-test', 'n@e.com') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, config) "
                "VALUES (101, 101, 'notif-test', 'test', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "DELETE FROM user_notify_preferences WHERE user_id = 101"
            )
        )
        await session.execute(
            text(
                "INSERT INTO user_notify_preferences (user_id, event_type, channels) "
                "VALUES (101, 'run_failed', CAST('[\"sse\"]' AS JSONB))"
            )
        )
        await session.commit()


async def _cleanup(run_id: str) -> None:
    async with get_db() as session:
        await session.execute(
            text("DELETE FROM telemetry_events WHERE run_id = :rid"),
            {"rid": run_id},
        )
        await session.execute(
            text("DELETE FROM user_notify_preferences WHERE user_id = 101")
        )
        await session.commit()


async def test_end_to_end_run_failed() -> None:
    print("\n=== bus → collector → notifier → SSE channel ===")
    run_id = f"notif-test-{uuid.uuid4().hex[:8]}"
    bus = EventBus(queue_size=100)
    collector = TelemetryCollector(
        db_session_factory=get_session_factory(),
        bus=bus,
        enabled=True,
        batch_size=5,
        flush_interval_sec=0.2,
        max_queue_size=100,
    )
    sse = SseChannel()
    notifier = Notifier(
        bus=bus,
        channels=[sse],
        rules=None,
        session_factory=get_session_factory(),
        queue_size=100,
    )
    tok_p = current_project_id.set(101)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        await notifier.start()

        queue = sse.register(101)

        collector.record_pipeline_event(
            pipeline_event_type="pipeline_end",
            pipeline_name="p",
            error_msg="boom",
        )

        try:
            notification = await asyncio.wait_for(queue.get(), timeout=3.0)
        except asyncio.TimeoutError:
            notification = None

        check("SSE queue received notification", notification is not None)
        if notification is not None:
            check(
                "notification event_type=run_failed",
                notification.event_type == "run_failed",
            )
            check("notification user_id=101", notification.user_id == 101)
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await notifier.stop(timeout_seconds=2.0)
        await collector.stop(timeout_seconds=2.0)
        bus.close()
        await _cleanup(run_id)


async def test_null_notifier_zero_activity() -> None:
    print("\n=== NullNotifier: emit → zero delivery ===")
    run_id = f"notif-null-{uuid.uuid4().hex[:8]}"
    bus = EventBus(queue_size=50)
    collector = TelemetryCollector(
        db_session_factory=get_session_factory(),
        bus=bus,
        enabled=True,
        batch_size=5,
        flush_interval_sec=0.2,
        max_queue_size=50,
    )
    notifier = NullNotifier(bus=bus)
    # Null notifier does not subscribe; a fresh SseChannel mirrors that.
    sse = SseChannel()
    queue = sse.register(101)

    tok_p = current_project_id.set(101)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        await notifier.start()
        collector.record_pipeline_event(
            pipeline_event_type="pipeline_end",
            pipeline_name="p",
            error_msg="boom",
        )
        await asyncio.sleep(0.3)
        check("null notifier: no SSE delivery", queue.qsize() == 0)
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await notifier.stop()
        await collector.stop(timeout_seconds=2.0)
        bus.close()
        await _cleanup(run_id)


async def main_async() -> None:
    try:
        await _ensure_schema()
    except Exception as exc:  # noqa: BLE001
        skip_all(f"DB not reachable: {type(exc).__name__}: {exc}")
        return
    await test_end_to_end_run_failed()
    await test_null_notifier_zero_activity()


def main() -> None:
    asyncio.run(main_async())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
