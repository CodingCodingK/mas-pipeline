"""Telemetry REST API tests using FastAPI TestClient.

Query functions are monkeypatched so these tests exercise routing, param
handling, 404 mapping, and auth — not the DB. The real DB path is covered
by test_telemetry_rest_integration.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_api_key  # noqa: F401 — import for side-effect

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


def test_run_summary_ok() -> None:
    print("\n=== GET /api/telemetry/runs/{run_id}/summary 200 ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_run_summary",
            AsyncMock(return_value={"run_id": "r1", "total_events": 3}),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/runs/r1/summary", headers=HEADERS)
                check("200", r.status_code == 200)
                check("body has run_id", r.json().get("run_id") == "r1")


def test_run_summary_404() -> None:
    print("\n=== missing run → 404 ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_run_summary",
            AsyncMock(side_effect=KeyError("run_id='x' has no telemetry events")),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/runs/x/summary", headers=HEADERS)
                check("404", r.status_code == 404)


def test_run_tree_ok() -> None:
    print("\n=== GET run tree ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_run_tree",
            AsyncMock(return_value={"run_id": "r1", "roots": [], "orphans": [], "spawns": []}),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/runs/r1/tree", headers=HEADERS)
                check("200", r.status_code == 200)
                check("roots in body", "roots" in r.json())


def test_run_agents_timeline_errors() -> None:
    print("\n=== run agents/timeline/errors ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_run_agents",
            AsyncMock(return_value=[{"agent_role": "coordinator"}]),
        ), patch(
            "src.telemetry.api.get_run_timeline",
            AsyncMock(return_value=[{"event_type": "llm_call"}]),
        ), patch(
            "src.telemetry.api.get_run_errors",
            AsyncMock(return_value=[]),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r1 = client.get("/api/telemetry/runs/r1/agents", headers=HEADERS)
                r2 = client.get("/api/telemetry/runs/r1/timeline", headers=HEADERS)
                r3 = client.get("/api/telemetry/runs/r1/errors", headers=HEADERS)
                check("agents 200", r1.status_code == 200 and len(r1.json()) == 1)
                check("timeline 200", r2.status_code == 200)
                check("errors 200 empty list", r3.status_code == 200 and r3.json() == [])


def test_session_summary_404() -> None:
    print("\n=== session summary missing ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_session_summary",
            AsyncMock(side_effect=KeyError("no events")),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/sessions/99/summary", headers=HEADERS)
                check("404", r.status_code == 404)


def test_session_tree_ok() -> None:
    print("\n=== session tree ok ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_session_tree",
            AsyncMock(return_value={"session_id": 42, "roots": [], "orphans": [], "spawns": []}),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/sessions/42/tree", headers=HEADERS)
                check("200", r.status_code == 200)
                check("session_id", r.json().get("session_id") == 42)


def test_project_cost_with_filters() -> None:
    print("\n=== project cost with query params ===")
    captured: dict = {}

    async def fake(project_id, from_, to_, group_by, pipeline):  # noqa: ARG001
        captured.update({
            "project_id": project_id,
            "from_": from_,
            "to_": to_,
            "group_by": group_by,
            "pipeline": pipeline,
        })
        return [{"key": "2026-04-11", "cost_usd": 0.05}]

    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch("src.telemetry.api.get_project_cost", side_effect=fake):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get(
                    "/api/telemetry/projects/7/cost",
                    params={
                        "from": "2026-04-10T00:00:00",
                        "to": "2026-04-12T00:00:00",
                        "group_by": "day",
                        "pipeline": "blog_generation",
                    },
                    headers=HEADERS,
                )
                check("200", r.status_code == 200)
                check("project_id captured", captured["project_id"] == 7)
                check("group_by day", captured["group_by"] == "day")
                check("pipeline filter", captured["pipeline"] == "blog_generation")
                check("from_ parsed", captured["from_"] is not None)


def test_project_cost_bad_group_by() -> None:
    print("\n=== bad group_by → 422 ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        app = _build_app()
        with TestClient(app) as client:
            r = client.get(
                "/api/telemetry/projects/1/cost",
                params={"group_by": "month"},
                headers=HEADERS,
            )
            check("422", r.status_code == 422)


def test_project_trends() -> None:
    print("\n=== project trends ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_project_trends",
            AsyncMock(return_value={
                "project_id": 1,
                "latency": [],
                "tokens": [],
                "cost": [],
            }),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/projects/1/trends", headers=HEADERS)
                check("200", r.status_code == 200)
                check("has latency", "latency" in r.json())


def test_reload_pricing_admin() -> None:
    print("\n=== admin reload-pricing ===")

    class _FakeCollector:
        def reload_pricing(self) -> int:
            return 7

    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch("src.telemetry.api.get_collector", return_value=_FakeCollector()):
            app = _build_app()
            with TestClient(app) as client:
                r = client.post(
                    "/api/admin/telemetry/reload-pricing", headers=HEADERS
                )
                check("200", r.status_code == 200)
                check("models_loaded == 7", r.json().get("models_loaded") == 7)


def test_auth_required() -> None:
    print("\n=== missing api key → 401 ===")
    with patch("src.api.auth.get_settings", return_value=_Settings()):
        with patch(
            "src.telemetry.api.get_run_summary",
            AsyncMock(return_value={}),
        ):
            app = _build_app()
            with TestClient(app) as client:
                r = client.get("/api/telemetry/runs/r1/summary")
                check("401 without key", r.status_code == 401)
                r2 = client.post("/api/admin/telemetry/reload-pricing")
                check("401 on admin", r2.status_code == 401)


if __name__ == "__main__":
    test_run_summary_ok()
    test_run_summary_404()
    test_run_tree_ok()
    test_run_agents_timeline_errors()
    test_session_summary_404()
    test_session_tree_ok()
    test_project_cost_with_filters()
    test_project_cost_bad_group_by()
    test_project_trends()
    test_reload_pricing_admin()
    test_auth_required()
    print(f"\n{'=' * 50}")
    print(f"passed={passed} failed={failed}")
    sys.exit(0 if failed == 0 else 1)
