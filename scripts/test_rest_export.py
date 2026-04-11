"""REST tests for src/api/export.py (Change 1.6).

PG required — creates real WorkflowRun rows in various states and hits the
mounted endpoint via an in-memory FastAPI app (no HTTP server).

Run: python scripts/test_rest_export.py
"""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from sqlalchemy import delete, text

from src.api.export import router as export_router
from src.db import get_db
from src.engine.run import (
    RunStatus,
    create_run,
    finish_run,
    update_run_status,
)
from src.models import Project, WorkflowRun


passed = 0
failed = 0


def section(name: str) -> None:
    print(f"\n=== {name} ===")


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


PROJECT_ID = 1


async def _ensure_project() -> None:
    async with get_db() as db:
        existing = await db.get(Project, PROJECT_ID)
        if existing is not None:
            return
        await db.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, status) "
                "VALUES (:id, 1, 'export-test', 'blog_generation', 'active')"
            ),
            {"id": PROJECT_ID},
        )


async def _cleanup() -> None:
    async with get_db() as db:
        await db.execute(delete(WorkflowRun).where(WorkflowRun.run_id.like("exp_%")))


async def _make_run(suffix: str, pipeline: str = "blog_generation") -> WorkflowRun:
    run = await create_run(project_id=PROJECT_ID, pipeline=pipeline)
    async with get_db() as db:
        await db.execute(
            text("UPDATE workflow_runs SET run_id = :new WHERE run_id = :old"),
            {"new": f"exp_{suffix}", "old": run.run_id},
        )
    run.run_id = f"exp_{suffix}"
    return run


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(export_router, prefix="/api")
    return app


async def run_tests() -> None:
    from fastapi.testclient import TestClient

    await _ensure_project()
    await _cleanup()

    # ── Happy path: completed run with final_output ──────────
    section("GET /api/runs/:id/export — happy path")

    run = await _make_run("ok1")
    await update_run_status(run.run_id, RunStatus.RUNNING)
    await finish_run(
        run.run_id,
        RunStatus.COMPLETED,
        result_payload={"final_output": "# Report\n\nhello"},
    )

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        with TestClient(_build_app()) as client:
            r = client.get(f"/api/runs/{run.run_id}/export")
            check("status 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
            check(
                "body is raw final_output bytes",
                r.content == b"# Report\n\nhello",
                repr(r.content),
            )
            check(
                "Content-Type markdown",
                r.headers.get("content-type", "").startswith("text/markdown"),
                r.headers.get("content-type", ""),
            )
            cd = r.headers.get("content-disposition", "")
            check("Content-Disposition has attachment", "attachment" in cd, cd)
            check(
                "Content-Disposition has ASCII filename with run_id_short",
                f'filename="blog_generation_exp_ok1.md"' in cd or 'filename="blog_generation_exp_ok1' in cd,
                cd,
            )
            check(
                "Content-Disposition has filename* UTF-8 form",
                "filename*=UTF-8''" in cd,
                cd,
            )

    # ── Non-ASCII pipeline name ──────────────────────────────
    section("non-ASCII pipeline name — dual filename forms")

    run2 = await _make_run("ok2", pipeline="博客生成")
    await update_run_status(run2.run_id, RunStatus.RUNNING)
    await finish_run(
        run2.run_id,
        RunStatus.COMPLETED,
        result_payload={"final_output": "中文内容"},
    )

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        with TestClient(_build_app()) as client:
            r = client.get(f"/api/runs/{run2.run_id}/export")
            check("status 200 for non-ASCII", r.status_code == 200)
            check("UTF-8 body roundtrip", r.content == "中文内容".encode("utf-8"))
            cd = r.headers.get("content-disposition", "")
            # ASCII fallback: 博客生成 → 4 underscores, then _exp_ok2
            check(
                "ASCII fallback collapses non-ASCII to _",
                'filename="____' in cd,
                cd,
            )
            # Extended form has percent-encoded filename
            encoded_name = quote("博客生成_exp_ok2.md", safe="")
            check(
                "filename* has percent-encoded non-ASCII",
                f"filename*=UTF-8''{encoded_name}" in cd,
                cd,
            )

    # ── 409: running run ────────────────────────────────────
    section("409 for non-completed runs")

    run3 = await _make_run("run3")
    await update_run_status(run3.run_id, RunStatus.RUNNING)

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        with TestClient(_build_app()) as client:
            r = client.get(f"/api/runs/{run3.run_id}/export")
            check("running → 409", r.status_code == 409, f"got {r.status_code}")
            check(
                "detail mentions 'running'",
                "running" in r.json().get("detail", ""),
                r.text,
            )

    run4 = await _make_run("run4")
    await update_run_status(run4.run_id, RunStatus.RUNNING)
    await finish_run(run4.run_id, RunStatus.FAILED)

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        with TestClient(_build_app()) as client:
            r = client.get(f"/api/runs/{run4.run_id}/export")
            check("failed → 409", r.status_code == 409)

    # ── 404: unknown run ────────────────────────────────────
    section("404 for unknown run_id")

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        with TestClient(_build_app()) as client:
            r = client.get("/api/runs/nonexistent_xyz/export")
            check("unknown → 404", r.status_code == 404)
            check(
                "detail == 'run not found'",
                r.json().get("detail") == "run not found",
                r.text,
            )

    # ── 404: completed but no final_output (legacy) ─────────
    section("404 for completed run missing final_output")

    run5 = await _make_run("legacy1")
    await update_run_status(run5.run_id, RunStatus.RUNNING)
    await finish_run(run5.run_id, RunStatus.COMPLETED)  # no payload

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        with TestClient(_build_app()) as client:
            r = client.get(f"/api/runs/{run5.run_id}/export")
            check("legacy → 404", r.status_code == 404)
            check(
                "distinct detail for legacy",
                r.json().get("detail") == "run completed but has no exportable output",
                r.text,
            )

    # ── 401: missing / bad API key ──────────────────────────
    section("401 when API key is required")

    run6 = await _make_run("auth1")
    await update_run_status(run6.run_id, RunStatus.RUNNING)
    await finish_run(
        run6.run_id,
        RunStatus.COMPLETED,
        result_payload={"final_output": "x"},
    )

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = ["secret-key"]
        with TestClient(_build_app()) as client:
            r = client.get(f"/api/runs/{run6.run_id}/export")
            check("missing key → 401", r.status_code == 401, f"got {r.status_code}")

            r = client.get(
                f"/api/runs/{run6.run_id}/export",
                headers={"X-API-Key": "wrong"},
            )
            check("wrong key → 401", r.status_code == 401)

            r = client.get(
                f"/api/runs/{run6.run_id}/export",
                headers={"X-API-Key": "secret-key"},
            )
            check("correct key → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    await _cleanup()


async def main() -> None:
    try:
        await run_tests()
    finally:
        print(f"\n{passed} passed, {failed} failed")
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
