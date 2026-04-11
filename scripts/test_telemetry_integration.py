"""Telemetry collector integration tests against real PG.

Writes events via the real TelemetryCollector + PG session factory and
asserts rows land in `telemetry_events`. Skips gracefully if PG is not
reachable (same pattern as other integration scripts).

Scenarios:
  1. Batched flush: record several events → rows appear
  2. turn_context → agent_turn row with contextvars linkage
  3. coordinator spawns researcher → agent_spawn + child agent_turn with
     spawned_by_spawn_id linking back
  4. disabled collector → zero rows
  5. pipeline error path → error event persisted
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
from src.llm.adapter import Usage
from src.telemetry import (
    NullTelemetryCollector,
    TelemetryCollector,
    current_project_id,
    current_run_id,
    current_session_id,
    current_spawn_id,
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
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def skip_all(reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  [SKIP] {reason}")


async def _ensure_project(project_id: int) -> None:
    async with get_db() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, name, email) "
                "VALUES (1, 'test', 'test@example.com') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, config) "
                "VALUES (:id, 1, :name, 'test', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": project_id, "name": f"telemetry-test-{project_id}"},
        )
        await session.commit()


async def _delete_run_events(run_id: str) -> None:
    async with get_db() as session:
        await session.execute(
            text("DELETE FROM telemetry_events WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        await session.commit()


async def _count_events(run_id: str, event_type: str | None = None) -> int:
    async with get_db() as session:
        if event_type is None:
            result = await session.execute(
                text("SELECT COUNT(*) FROM telemetry_events WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        else:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM telemetry_events "
                    "WHERE run_id = :run_id AND event_type = :et"
                ),
                {"run_id": run_id, "et": event_type},
            )
        return int(result.scalar() or 0)


async def _fetch_events(run_id: str) -> list[dict]:
    async with get_db() as session:
        result = await session.execute(
            text(
                "SELECT event_type, agent_role, session_id, payload "
                "FROM telemetry_events WHERE run_id = :run_id ORDER BY id ASC"
            ),
            {"run_id": run_id},
        )
        return [dict(r) for r in result.mappings().all()]


def _make_collector(**overrides) -> TelemetryCollector:
    bus = EventBus(queue_size=100)
    return TelemetryCollector(
        db_session_factory=get_session_factory(),
        bus=bus,
        enabled=overrides.pop("enabled", True),
        preview_length=30,
        batch_size=overrides.pop("batch_size", 5),
        flush_interval_sec=overrides.pop("flush_interval_sec", 0.2),
        max_queue_size=100,
        pricing_table_path="config/pricing.yaml",
    )


# ── Tests ─────────────────────────────────────────────────


async def test_batched_flush_persists_rows() -> None:
    print("\n=== batched flush writes rows to PG ===")
    run_id = f"tele-test-{uuid.uuid4().hex[:8]}"
    collector = _make_collector()
    tok_p = current_project_id.set(1)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        for _ in range(6):
            collector.record_hook_event(
                hook_type="PreToolUse", decision="allow", latency_ms=10
            )
        await asyncio.sleep(0.5)
        await collector.stop(timeout_seconds=5.0)
        count = await _count_events(run_id, "hook_event")
        check("6 hook_event rows persisted", count == 6, detail=f"got {count}")
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await _delete_run_events(run_id)


async def test_turn_context_persists_agent_turn() -> None:
    print("\n=== turn_context writes agent_turn row ===")
    run_id = f"tele-test-{uuid.uuid4().hex[:8]}"
    collector = _make_collector()
    tok_p = current_project_id.set(1)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        async with collector.turn_context(
            agent_role="assistant",
            input_preview="hello",
            session_id=12345,
            project_id=1,
        ) as capture:
            collector.record_llm_call(
                provider="anthropic",
                model="claude-opus-4-6",
                usage=Usage(input_tokens=100, output_tokens=50),
                latency_ms=400,
                finish_reason="stop",
            )
            capture["output"] = "world"
            capture["message_count_delta"] = 2
        await asyncio.sleep(0.4)
        await collector.stop(timeout_seconds=5.0)
        events = await _fetch_events(run_id)
        turn_rows = [e for e in events if e["event_type"] == "agent_turn"]
        llm_rows = [e for e in events if e["event_type"] == "llm_call"]
        check("1 agent_turn persisted", len(turn_rows) == 1)
        check("1 llm_call persisted", len(llm_rows) == 1)
        if turn_rows:
            check(
                "agent_turn agent_role=assistant",
                turn_rows[0]["agent_role"] == "assistant",
            )
            check(
                "agent_turn session_id=12345",
                turn_rows[0]["session_id"] == 12345,
            )
        if llm_rows:
            check(
                "llm_call parent_turn_id set",
                (llm_rows[0]["payload"] or {}).get("parent_turn_id") is not None,
            )
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await _delete_run_events(run_id)


async def test_spawn_child_linkage() -> None:
    print("\n=== spawn → child turn linked via spawn_id ===")
    run_id = f"tele-test-{uuid.uuid4().hex[:8]}"
    collector = _make_collector()
    tok_p = current_project_id.set(1)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        # Parent turn
        async with collector.turn_context(
            agent_role="coordinator",
            input_preview="orchestrate",
            project_id=1,
        ):
            spawn_id = uuid.uuid4().hex
            collector.record_agent_spawn(
                parent_role="coordinator",
                child_role="researcher",
                task_preview="research topic",
                spawn_id=spawn_id,
            )
            # Simulate child task inheriting current_spawn_id (create_task path)
            async def child() -> None:
                current_spawn_id.set(spawn_id)
                async with collector.turn_context(
                    agent_role="researcher",
                    input_preview="research topic",
                    project_id=1,
                ):
                    pass
            await asyncio.create_task(child())
        await asyncio.sleep(0.4)
        await collector.stop(timeout_seconds=5.0)
        events = await _fetch_events(run_id)
        spawn_rows = [e for e in events if e["event_type"] == "agent_spawn"]
        turn_rows = [e for e in events if e["event_type"] == "agent_turn"]
        check("1 spawn event", len(spawn_rows) == 1)
        check("2 agent_turn events", len(turn_rows) == 2)
        researcher_turn = next(
            (t for t in turn_rows if t["agent_role"] == "researcher"), None
        )
        check("researcher turn present", researcher_turn is not None)
        if researcher_turn:
            linked = (researcher_turn["payload"] or {}).get("spawned_by_spawn_id")
            check(
                "researcher.spawned_by_spawn_id == spawn_id",
                linked == spawn_id,
                detail=f"got {linked!r}",
            )
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await _delete_run_events(run_id)


async def test_disabled_writes_nothing() -> None:
    print("\n=== disabled collector persists nothing ===")
    run_id = f"tele-test-{uuid.uuid4().hex[:8]}"
    collector = _make_collector(enabled=False)
    tok_p = current_project_id.set(1)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        collector.record_hook_event(
            hook_type="PreToolUse", decision="allow", latency_ms=10
        )
        collector.record_llm_call(
            provider="anthropic", model="claude-opus-4-6",
            usage=Usage(input_tokens=1, output_tokens=1),
            latency_ms=1, finish_reason="stop",
        )
        await asyncio.sleep(0.3)
        await collector.stop(timeout_seconds=2.0)
        count = await _count_events(run_id)
        check("zero rows when disabled", count == 0, detail=f"got {count}")
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        # safety sweep (should already be empty)
        await _delete_run_events(run_id)


async def test_null_collector_interchangeable() -> None:
    print("\n=== NullTelemetryCollector safe to use ===")
    null = NullTelemetryCollector(bus=EventBus())
    await null.start()
    null.record_hook_event(hook_type="X", decision="allow", latency_ms=1)
    async with null.turn_context(
        agent_role="assistant", input_preview="x", project_id=1
    ) as cap:
        cap["output"] = "y"
    count = null.reload_pricing()
    await null.stop()
    check("null reload_pricing == 0", count == 0)
    check("null records nothing (no exception)", True)


async def test_error_event_persists() -> None:
    print("\n=== record_error persists error row ===")
    run_id = f"tele-test-{uuid.uuid4().hex[:8]}"
    collector = _make_collector()
    tok_p = current_project_id.set(1)
    tok_r = current_run_id.set(run_id)
    try:
        await collector.start()
        try:
            raise RuntimeError("simulated node failure")
        except RuntimeError as exc:
            collector.record_error(source="pipeline", exc=exc)
        await asyncio.sleep(0.4)
        await collector.stop(timeout_seconds=5.0)
        count = await _count_events(run_id, "error")
        check("1 error row persisted", count == 1, detail=f"got {count}")
    finally:
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await _delete_run_events(run_id)


# ── Main ──────────────────────────────────────────────────


async def main_async() -> None:
    try:
        await _ensure_project(1)
    except Exception as exc:  # noqa: BLE001
        skip_all(f"DB not reachable: {type(exc).__name__}: {exc}")
        return

    await test_batched_flush_persists_rows()
    await test_turn_context_persists_agent_turn()
    await test_spawn_child_linkage()
    await test_disabled_writes_nothing()
    await test_null_collector_interchangeable()
    await test_error_event_persists()


def main() -> None:
    asyncio.run(main_async())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        sys.exit(1)
    if skipped and not passed:
        print("All tests skipped (environment unavailable).")
        return
    print("All checks passed!")


if __name__ == "__main__":
    main()
