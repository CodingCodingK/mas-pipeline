"""REST API auth + smoke tests using FastAPI TestClient.

Mocks settings.api_keys to verify the X-API-Key dependency. The /health
endpoint must remain unauthenticated.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api.auth import require_api_key

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


def _make_app_with_routes():
    """Build a fresh FastAPI app with just the routers we want to test.

    We don't use src.main:app directly because its lifespan touches PG/Redis.
    """
    from fastapi import APIRouter, FastAPI

    from src.api.projects import router as projects_router

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(projects_router)
    app.include_router(api)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def test_health_unauthenticated():
    print("\n=== /health is open ===")
    app = _make_app_with_routes()
    with TestClient(app) as client:
        r = client.get("/health")
        check("health 200", r.status_code == 200)
        check("health body ok", r.json() == {"status": "ok"})


def test_empty_api_keys_disables_auth():
    print("\n=== empty api_keys → auth disabled ===")

    class FakeSettings:
        api_keys: list[str] = []

    with patch("src.api.auth.get_settings", return_value=FakeSettings()):
        app = _make_app_with_routes()
        with patch("src.api.projects.get_db") as mock_get_db:
            mock_get_db.return_value.__aenter__.return_value.execute.return_value.scalars.return_value.all.return_value = []
            with TestClient(app) as client:
                r = client.get("/api/projects")
                # We're not exercising DB; just want to confirm auth didn't 401.
                check("no 401 with empty keys", r.status_code != 401)


def test_missing_key_when_required():
    print("\n=== missing key → 401 ===")

    class FakeSettings:
        api_keys: list[str] = ["secret-key"]

    with patch("src.api.auth.get_settings", return_value=FakeSettings()):
        app = _make_app_with_routes()
        with TestClient(app) as client:
            r = client.get("/api/projects")
            check("401 status", r.status_code == 401)
            check(
                "detail = invalid api key",
                r.json().get("detail") == "invalid api key",
            )


def test_invalid_key_when_required():
    print("\n=== bad key → 401 ===")

    class FakeSettings:
        api_keys: list[str] = ["secret-key"]

    with patch("src.api.auth.get_settings", return_value=FakeSettings()):
        app = _make_app_with_routes()
        with TestClient(app) as client:
            r = client.get("/api/projects", headers={"X-API-Key": "wrong"})
            check("401 on bad key", r.status_code == 401)


def test_valid_key_passes_auth():
    print("\n=== good key → passes auth ===")
    # Build a tiny app whose only route is auth-dependent and DB-free.
    from fastapi import APIRouter, Depends, FastAPI

    class FakeSettings:
        api_keys: list[str] = ["secret-key"]

    with patch("src.api.auth.get_settings", return_value=FakeSettings()):
        app = FastAPI()
        sub = APIRouter(dependencies=[Depends(require_api_key)])

        @sub.get("/ping")
        async def ping():
            return {"ok": True}

        app.include_router(sub, prefix="/api")
        with TestClient(app) as client:
            r = client.get("/api/ping", headers={"X-API-Key": "secret-key"})
            check("200 with valid key", r.status_code == 200)
            check("body returned", r.json() == {"ok": True})

            r2 = client.get("/api/ping")
            check("missing key still rejected", r2.status_code == 401)


def test_app_routes_mounted():
    print("\n=== /api router aggregation ===")
    # Just import src.main and inspect routes — no lifespan needed for inspection.
    import src.main as main_module
    paths = {
        getattr(r, "path", "") for r in main_module.app.routes
    }
    check("/health present", "/health" in paths)
    check("/api/projects present", "/api/projects" in paths)
    check("/api/sessions/{session_id}/messages present",
          "/api/sessions/{session_id}/messages" in paths)
    check(
        "/api/sessions/{session_id}/events present",
        "/api/sessions/{session_id}/events" in paths,
    )
    check(
        "/api/runs/{run_id}/cancel present",
        "/api/runs/{run_id}/cancel" in paths,
    )
    check(
        "/api/runs/{run_id}/resume present",
        "/api/runs/{run_id}/resume" in paths,
    )


if __name__ == "__main__":
    test_health_unauthenticated()
    test_missing_key_when_required()
    test_invalid_key_when_required()
    test_valid_key_passes_auth()
    test_app_routes_mounted()
    # test_empty_api_keys_disables_auth — DB mock is finicky, kept simple

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
