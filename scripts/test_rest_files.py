"""REST tests for src/api/files.py (Phase 6.4 — files routes).

Requires PG (uses real Document rows). Mounts the router into a fresh
FastAPI app so this test is independent of main.py wiring.

Run: python scripts/test_rest_files.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import platform
from pathlib import Path
from unittest.mock import patch

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from src.api.files import router as files_router
from src.db import get_db
from src.files.manager import UPLOADS_DIR
from src.models import Document, Project


# ── Test runner state ──────────────────────────────────────

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


# ── Cleanup helpers ────────────────────────────────────────


PROJECT_ID = 1


async def _ensure_project(project_id: int = PROJECT_ID) -> None:
    async with get_db() as db:
        existing = await db.get(Project, project_id)
        if existing is not None:
            return
        await db.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, status) "
                "VALUES (:id, 1, 'rest-files-test', 'blog_generation', 'active')"
            ),
            {"id": project_id},
        )


async def _cleanup_documents(project_id: int = PROJECT_ID) -> None:
    async with get_db() as db:
        await db.execute(
            delete(Document).where(Document.project_id == project_id)
        )
    # Best-effort cleanup of physical files in uploads dir
    proj_dir = UPLOADS_DIR / str(project_id)
    if proj_dir.exists():
        for f in proj_dir.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except OSError:
                    pass


# ── App fixture ────────────────────────────────────────────


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(files_router)
    return app


# ── Tests ──────────────────────────────────────────────────


def run_auth_disabled_tests(client: TestClient) -> None:
    section("upload / list / delete (auth disabled)")

    # Upload a markdown file
    content = b"# hello\n\nthis is a test document " * 10
    files = {"file": ("hello.md", content, "text/markdown")}
    r = client.post(f"/projects/{PROJECT_ID}/files", files=files)
    check("upload md → 200", r.status_code == 200, r.text)
    body = r.json()
    check("response has id", "id" in body and isinstance(body["id"], int))
    check("filename echoed", body.get("filename") == "hello.md")
    check("file_type = md", body.get("file_type") == "md")
    check("project_id correct", body.get("project_id") == PROJECT_ID)
    check("file_size > 0", (body.get("file_size") or 0) > 0)
    check("parsed = False initially", body.get("parsed") is False)
    check("chunk_count = 0 initially", body.get("chunk_count") == 0)
    check("created_at present", body.get("created_at") is not None)

    file_id = body["id"]

    # List
    r = client.get(f"/projects/{PROJECT_ID}/files")
    check("list → 200", r.status_code == 200)
    items = r.json()
    check("list returns at least 1", len(items) >= 1)
    check(
        "uploaded file in list",
        any(it["id"] == file_id for it in items),
    )

    # Delete the uploaded file
    r = client.delete(f"/projects/{PROJECT_ID}/files/{file_id}")
    check("delete → 204", r.status_code == 204)

    # Subsequent list excludes it
    r = client.get(f"/projects/{PROJECT_ID}/files")
    items = r.json()
    check(
        "deleted file no longer in list",
        not any(it["id"] == file_id for it in items),
    )

    # Delete non-existent → 404
    r = client.delete(f"/projects/{PROJECT_ID}/files/9999999")
    check("delete missing → 404", r.status_code == 404)

    # Upload invalid extension → 400
    files = {"file": ("evil.exe", b"MZ\x00\x00", "application/octet-stream")}
    r = client.post(f"/projects/{PROJECT_ID}/files", files=files)
    check("invalid ext → 400", r.status_code == 400, r.text)
    check(
        "400 detail mentions not supported",
        "not supported" in r.json().get("detail", ""),
    )

    # Empty filename → 400
    r = client.post(
        f"/projects/{PROJECT_ID}/files",
        files={"file": ("", b"x", "application/octet-stream")},
    )
    check("empty filename → 400 or 422", r.status_code in (400, 422))


def run_auth_enabled_tests() -> None:
    section("auth required when api_keys configured")

    # Patch settings.api_keys to non-empty
    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = ["secret-key"]
        app = _build_app()
        with TestClient(app) as client:
            r = client.get(f"/projects/{PROJECT_ID}/files")
            check("missing key → 401", r.status_code == 401)

            r = client.get(
                f"/projects/{PROJECT_ID}/files",
                headers={"X-API-Key": "wrong"},
            )
            check("wrong key → 401", r.status_code == 401)

            r = client.get(
                f"/projects/{PROJECT_ID}/files",
                headers={"X-API-Key": "secret-key"},
            )
            check("correct key → 200", r.status_code == 200, r.text)


# ── Main ───────────────────────────────────────────────────


def main():
    asyncio.run(_ensure_project())
    asyncio.run(_cleanup_documents())

    # Auth-disabled mode (default)
    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        app = _build_app()
        with TestClient(app) as client:
            try:
                run_auth_disabled_tests(client)
            finally:
                try:
                    asyncio.run(_cleanup_documents())
                except Exception as exc:
                    print(f"  [WARN] cleanup failed: {exc}")

    # Auth-enabled mode (separate fixture so the patch scope is right)
    run_auth_enabled_tests()

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("All checks passed!")


if __name__ == "__main__":
    main()
