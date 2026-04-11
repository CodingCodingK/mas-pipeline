"""Telemetry REST integration tests: seed events via the real collector
into PG, then hit the /api/telemetry/* endpoints through TestClient so
the full HTTP → query → DB path is exercised.

Skips gracefully if PG isn't reachable.
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

from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.db import get_db, get_session_factory
from src.events.bus import EventBus
from src.llm.adapter import Usage
from src.telemetry import (
    TelemetryCollector,
    current_project_id,
    current_run_id,
    current_session_id,
    current_spawn_id,
    set_collector,
)

passed = 0
failed = 0
skipped = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
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


class _Settings:
    api_keys: list[str] = ["k1"]


HEADERS = {"X-API-Key": "k1"}


def _build_app() -> FastAPI:
    from src.telemetry.api import admin_router, router

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(router)
    api.include_router(admin_router)
    app.include_router(api)
    return app


async def _ensure_seed_project() -> None:
    async with get_db() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, name, email) VALUES (1, 'test', 'test@example.com') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, config) "
                "VALUES (1, 1, 'telemetry-rest-test', 'test', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.commit()


async def _delete_run(run_id: str) -> None:
    async with get_db() as session:
        await session.execute(
            text("DELETE FROM telemetry_events WHERE run_id = :r"),
            {"r": run_id},
        )
        await session.commit()


async def _seed_run(run_id: str, session_id: int) -> None:
    """Seed a fake run + session with coordinator → researcher spawn.

    Events emitted:
      - agent_turn coordinator + llm_call
      - agent_spawn
      - agent_turn researcher + llm_call
      - pipeline_start + pipeline_end
    """
    bus = EventBus(queue_size=50)
    collector = TelemetryCollector(
        db_session_factory=get_session_factory(),
        bus=bus,
        enabled=True,
        preview_length=30,
        batch_size=2,
        flush_interval_sec=0.1,
        max_queue_size=50,
        pricing_table_path="config/pricing.yaml",
    )
    set_collector(collector)
    await collector.start()

    tok_p = current_project_id.set(1)
    tok_r = current_run_id.set(run_id)
    tok_s = current_session_id.set(session_id)
    try:
        collector.record_pipeline_event(
            pipeline_event_type="pipeline_start",
            pipeline_name="blog_generation",
        )

        # Coordinator turn
        async with collector.turn_context(
            agent_role="coordinator",
            input_preview="write a blog",
            session_id=session_id,
            project_id=1,
        ) as cap:
            collector.record_llm_call(
                provider="anthropic",
                model="claude-opus-4-6",
                usage=Usage(input_tokens=500, output_tokens=200),
                latency_ms=1200,
                finish_reason="stop",
            )
            spawn_id = uuid.uuid4().hex
            collector.record_agent_spawn(
                parent_role="coordinator",
                child_role="researcher",
                task_preview="gather sources",
                spawn_id=spawn_id,
            )

            async def child():
                current_spawn_id.set(spawn_id)
                async with collector.turn_context(
                    agent_role="researcher",
                    input_preview="gather sources",
                    session_id=session_id,
                    project_id=1,
                ):
                    collector.record_llm_call(
                        provider="anthropic",
                        model="claude-sonnet-4-6",
                        usage=Usage(input_tokens=300, output_tokens=100),
                        latency_ms=800,
                        finish_reason="stop",
                    )
            await asyncio.create_task(child())
            cap["output"] = "ok"
            cap["message_count_delta"] = 3

        collector.record_pipeline_event(
            pipeline_event_type="pipeline_end",
            pipeline_name="blog_generation",
        )
        await asyncio.sleep(0.3)
    finally:
        current_session_id.reset(tok_s)
        current_run_id.reset(tok_r)
        current_project_id.reset(tok_p)
        await collector.stop(timeout_seconds=5.0)


# ── Tests ──────────────────────────────────────────────────


def test_run_summary_and_tree(run_id: str) -> None:
    print("\n=== run summary + tree via REST ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        app = _build_app()
        with TestClient(app) as client:
            r = client.get(f"/api/telemetry/runs/{run_id}/summary", headers=HEADERS)
            check("summary 200", r.status_code == 200, detail=r.text)
            body = r.json()
            check("llm_calls == 2", body.get("llm_calls") == 2)
            check("total_input_tokens == 800", body.get("total_input_tokens") == 800)
            check("total_output_tokens == 300", body.get("total_output_tokens") == 300)
            check("cost > 0", body.get("total_cost_usd", 0) > 0)

            rt = client.get(f"/api/telemetry/runs/{run_id}/tree", headers=HEADERS)
            check("tree 200", rt.status_code == 200)
            tree = rt.json()
            check("1 root turn", len(tree.get("roots", [])) == 1)
            root = tree["roots"][0]
            check("root role coordinator", root.get("agent_role") == "coordinator")
            check("1 child turn", len(root.get("child_turns", [])) == 1)
            if root.get("child_turns"):
                child = root["child_turns"][0]
                check("child role researcher", child.get("agent_role") == "researcher")


def test_run_agents_and_errors(run_id: str) -> None:
    print("\n=== run agents + errors via REST ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        app = _build_app()
        with TestClient(app) as client:
            r = client.get(f"/api/telemetry/runs/{run_id}/agents", headers=HEADERS)
            check("agents 200", r.status_code == 200)
            agents = r.json()
            roles = {a["agent_role"] for a in agents}
            check("coordinator + researcher rolled up", {"coordinator", "researcher"} <= roles)

            e = client.get(f"/api/telemetry/runs/{run_id}/errors", headers=HEADERS)
            check("errors 200 empty", e.status_code == 200 and e.json() == [])


def test_session_tree(run_id: str, session_id: int) -> None:
    print("\n=== session tree via REST ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        app = _build_app()
        with TestClient(app) as client:
            r = client.get(
                f"/api/telemetry/sessions/{session_id}/tree", headers=HEADERS
            )
            check("200", r.status_code == 200)
            tree = r.json()
            check("has roots or orphans", "roots" in tree)


def test_project_cost_groupby_day() -> None:
    print("\n=== project cost group_by=day ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        app = _build_app()
        with TestClient(app) as client:
            r = client.get(
                "/api/telemetry/projects/1/cost",
                params={"group_by": "day"},
                headers=HEADERS,
            )
            check("200", r.status_code == 200)
            buckets = r.json()
            check("at least 1 bucket", len(buckets) >= 1, detail=str(buckets))
            total_cost = sum(b.get("cost_usd", 0) for b in buckets)
            check("aggregated cost > 0", total_cost > 0)


def test_reload_pricing_admin() -> None:
    print("\n=== admin reload-pricing via REST ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        app = _build_app()
        with TestClient(app) as client:
            r = client.post("/api/admin/telemetry/reload-pricing", headers=HEADERS)
            check("200", r.status_code == 200)
            check("models_loaded >= 1", r.json().get("models_loaded", 0) >= 1)


# ── Main ───────────────────────────────────────────────────


async def main_async() -> None:
    run_id = f"tele-rest-{uuid.uuid4().hex[:8]}"
    session_id = 90001

    try:
        await _ensure_seed_project()
    except Exception as exc:  # noqa: BLE001
        skip_all(f"DB not reachable: {type(exc).__name__}: {exc}")
        return

    try:
        await _seed_run(run_id, session_id)

        test_run_summary_and_tree(run_id)
        test_run_agents_and_errors(run_id)
        test_session_tree(run_id, session_id)
        test_project_cost_groupby_day()
        test_reload_pricing_admin()
    finally:
        await _delete_run(run_id)


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
