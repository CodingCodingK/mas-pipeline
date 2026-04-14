"""Integration test for src/bench/queries.py against a real PostgreSQL.

Inserts hand-crafted `telemetry_events` rows under a dedicated dummy
run_id, runs each of the six dimension queries, asserts shape + numbers,
then cleans up. Skips gracefully if PG is not reachable (same pattern
as scripts/test_telemetry_integration.py).

Run:
    python scripts/test_bench_queries.py
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.bench import queries
from src.db import get_db

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


RUN_ID = f"bench-qtest-{uuid.uuid4().hex[:8]}"
PROJECT_ID = 999_001
T0 = datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)


async def _ensure_project() -> None:
    async with get_db() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, name, email) "
                "VALUES (999, 'bench-test', 'bench@test.local') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, config) "
                "VALUES (:id, 999, :name, 'test', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": PROJECT_ID, "name": f"bench-test-{PROJECT_ID}"},
        )
        await session.commit()


async def _insert_event(
    session,
    *,
    event_type: str,
    ts: datetime,
    payload: dict,
    agent_role: str | None = None,
    session_id: int | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO telemetry_events "
            "(ts, event_type, project_id, run_id, session_id, agent_role, payload) "
            "VALUES (:ts, :et, :pid, :rid, :sid, :role, CAST(:payload AS JSONB))"
        ),
        {
            "ts": ts,
            "et": event_type,
            "pid": PROJECT_ID,
            "rid": RUN_ID,
            "sid": session_id,
            "role": agent_role,
            "payload": json.dumps(payload, default=str),
        },
    )


async def _seed_fixtures() -> None:
    """Insert a controlled event set we can assert on.

    Shape:
      llm_call × 4 — mix of providers/models/latencies for percentile math
      tool_call × 5 — 3 shell (1 failure), 2 search_docs (both success)
      compact × 2 — one auto (0.5 ratio), one micro (0.8 ratio)
      agent_spawn × 3 — coordinator spawns 3 researchers
      agent_turn × 4 — overlapping intervals to test sweep-line (max=3)
    """
    async with get_db() as session:
        # 4 llm_call rows: latencies 100/200/800/1600 ms.
        for i, (lat, prov, model, in_t, out_t, cost) in enumerate([
            (100, "openai_compat", "gpt-5.4", 100, 50, 0.001),
            (200, "openai_compat", "gpt-5.4", 200, 100, 0.002),
            (800, "mock", "mock-llm", 500, 300, 0.0),
            (1600, "mock", "mock-llm", 800, 400, 0.0),
        ]):
            await _insert_event(
                session,
                event_type="llm_call",
                ts=T0 + timedelta(seconds=i),
                payload={
                    "provider": prov,
                    "model": model,
                    "input_tokens": in_t,
                    "output_tokens": out_t,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "latency_ms": lat,
                    "finish_reason": "stop",
                    "cost_usd": cost,
                    "turn_id": f"turn-{i}",
                    "parent_turn_id": f"turn-{i}",
                },
            )

        # 5 tool_call: 3 shell (1 failing), 2 search_docs
        tool_fixtures = [
            ("shell", 50, True),
            ("shell", 150, True),
            ("shell", 300, False),
            ("search_docs", 400, True),
            ("search_docs", 600, True),
        ]
        for i, (name, dur, ok) in enumerate(tool_fixtures):
            await _insert_event(
                session,
                event_type="tool_call",
                ts=T0 + timedelta(seconds=10 + i),
                payload={
                    "tool_name": name,
                    "args_preview": "...",
                    "duration_ms": dur,
                    "success": ok,
                    "error_type": None if ok else "RuntimeError",
                    "error_msg": None if ok else "boom",
                    "parent_turn_id": "turn-0",
                },
            )

        # 2 compact events: auto (0.5 ratio) + micro (0.8 ratio)
        await _insert_event(
            session,
            event_type="compact",
            ts=T0 + timedelta(seconds=30),
            payload={
                "trigger": "auto",
                "before_tokens": 10000,
                "after_tokens": 5000,
                "ratio": 0.5,
                "duration_ms": 1500,
                "turn_index": 5,
                "parent_turn_id": "turn-5",
            },
        )
        await _insert_event(
            session,
            event_type="compact",
            ts=T0 + timedelta(seconds=35),
            payload={
                "trigger": "micro",
                "before_tokens": 1000,
                "after_tokens": 800,
                "ratio": 0.8,
                "duration_ms": 20,
                "turn_index": 3,
                "parent_turn_id": "turn-3",
            },
        )

        # 3 agent_spawn rows: coordinator spawns 3 researchers
        for i in range(3):
            await _insert_event(
                session,
                event_type="agent_spawn",
                ts=T0 + timedelta(seconds=40 + i),
                payload={
                    "spawn_id": f"spawn-{i}",
                    "parent_role": "coordinator",
                    "child_role": "researcher",
                    "task_preview": f"task {i}",
                    "parent_turn_id": "turn-0",
                },
            )

        # 4 agent_turn rows with overlapping intervals.
        # t=50–55: turn A | t=52–58: turn B | t=53–56: turn C | t=60–62: turn D
        # Peak concurrency = 3 (at t=53–55).
        turn_intervals = [
            (50, 55),
            (52, 58),
            (53, 56),
            (60, 62),
        ]
        for i, (start, end) in enumerate(turn_intervals):
            start_ts = T0 + timedelta(seconds=start)
            end_ts = T0 + timedelta(seconds=end)
            await _insert_event(
                session,
                event_type="agent_turn",
                ts=start_ts,
                agent_role="researcher",
                payload={
                    "turn_id": f"turn-fanout-{i}",
                    "agent_role": "researcher",
                    "turn_index": i,
                    "started_at": start_ts.isoformat(),
                    "ended_at": end_ts.isoformat(),
                    "duration_ms": int((end - start) * 1000),
                    "message_count_delta": 2,
                    "stop_reason": "completed",
                    "input_preview": "",
                    "output_preview": "",
                    "spawned_by_spawn_id": f"spawn-{i % 3}",
                },
            )

        await session.commit()


async def _cleanup() -> None:
    async with get_db() as session:
        await session.execute(
            text("DELETE FROM telemetry_events WHERE run_id = :rid"),
            {"rid": RUN_ID},
        )
        await session.commit()


async def _run_tests() -> None:
    print("\n[llm_latency]")
    async with get_db() as session:
        res = await queries.llm_latency(session, run_id=RUN_ID)
    check("count == 4", res["count"] == 4, f"got {res['count']}")
    check("p50 between 200 and 800", 200 <= res["p50_ms"] <= 800)
    check("p95 close to 1600", abs(res["p95_ms"] - 1520) < 100,
          f"got {res['p95_ms']}")
    check(
        "by_provider has openai_compat and mock",
        "openai_compat" in res["by_provider"] and "mock" in res["by_provider"],
    )
    check(
        "by_model has gpt-5.4 with 2 calls",
        res["by_model"].get("gpt-5.4", {}).get("count") == 2,
    )

    print("\n[token_cost]")
    async with get_db() as session:
        res = await queries.token_cost(session, run_id=RUN_ID)
    check("calls == 4", res["calls"] == 4)
    check("input_tokens == 1600", res["input_tokens"] == 1600,
          f"got {res['input_tokens']}")
    check("output_tokens == 850", res["output_tokens"] == 850,
          f"got {res['output_tokens']}")
    check("cost_usd == 0.003", abs(res["cost_usd"] - 0.003) < 1e-9,
          f"got {res['cost_usd']}")
    check("missing_pricing_calls == 0", res["missing_pricing_calls"] == 0)

    print("\n[tool_rtt]")
    async with get_db() as session:
        res = await queries.tool_rtt(session, run_id=RUN_ID)
    check("total count == 5", res["count"] == 5)
    check(
        "overall failure rate == 0.2",
        abs(res["failure_rate"] - 0.2) < 1e-9,
        f"got {res['failure_rate']}",
    )
    shell = res["by_tool"].get("shell", {})
    check("shell count == 3", shell.get("count") == 3)
    check("shell failures == 1", shell.get("failures") == 1)
    search = res["by_tool"].get("search_docs", {})
    check("search_docs count == 2", search.get("count") == 2)
    check("search_docs failures == 0", search.get("failures") == 0)

    print("\n[rag_latency]")
    async with get_db() as session:
        res = await queries.rag_latency(session, run_id=RUN_ID)
    check("rag count == 2", res["count"] == 2)
    # search_docs total=1000 ms, all tools total=50+150+300+400+600=1500 ms
    check(
        "share_of_tool_ms ≈ 1000/1500",
        abs(res["share_of_tool_ms"] - (1000 / 1500)) < 1e-6,
        f"got {res['share_of_tool_ms']}",
    )

    print("\n[compact_stats]")
    async with get_db() as session:
        res = await queries.compact_stats(session, run_id=RUN_ID)
    check("count == 2", res["count"] == 2)
    auto = res["by_trigger"].get("auto", {})
    check("auto count == 1", auto.get("count") == 1)
    check("auto mean_ratio == 0.5", abs(auto.get("mean_ratio", 0) - 0.5) < 1e-9)
    check("auto mean_before == 10000", auto.get("mean_before") == 10000)

    print("\n[subagent_fanout]")
    async with get_db() as session:
        res = await queries.subagent_fanout(session, run_id=RUN_ID)
    check(
        "max_concurrent == 3",
        res["max_concurrent"] == 3,
        f"got {res['max_concurrent']}",
    )
    check("total_spawns == 3", res["total_spawns"] == 3)
    check(
        "avg_fanout_per_parent == 3.0",
        abs(res["avg_fanout_per_parent"] - 3.0) < 1e-9,
    )

    print("\n[all_dimensions]")
    async with get_db() as session:
        res = await queries.all_dimensions(session, run_id=RUN_ID)
    expected_keys = {
        "llm_latency", "token_cost", "tool_rtt",
        "rag_latency", "compact_stats", "subagent_fanout",
    }
    check(
        "all six keys present",
        set(res.keys()) == expected_keys,
        f"got {set(res.keys())}",
    )


async def _empty_case_tests() -> None:
    """Queries against a non-existent run must return zero-valued shapes."""
    empty_run = f"empty-{uuid.uuid4().hex[:8]}"
    print("\n[empty case: llm_latency]")
    async with get_db() as session:
        res = await queries.llm_latency(session, run_id=empty_run)
    check("empty count == 0", res["count"] == 0)
    check("empty p95 == 0", res["p95_ms"] == 0.0)

    print("\n[empty case: subagent_fanout]")
    async with get_db() as session:
        res = await queries.subagent_fanout(session, run_id=empty_run)
    check("empty max_concurrent == 0", res["max_concurrent"] == 0)
    check("empty total_spawns == 0", res["total_spawns"] == 0)


async def main() -> int:
    try:
        await _ensure_project()
    except Exception as exc:
        skip_all(f"PG not reachable: {exc}")
        print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
        return 0

    try:
        await _seed_fixtures()
        await _run_tests()
        await _empty_case_tests()
    finally:
        try:
            await _cleanup()
        except Exception as exc:
            print(f"  [WARN] cleanup failed: {exc}")

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
