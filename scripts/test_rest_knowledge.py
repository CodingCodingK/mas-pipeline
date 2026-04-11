"""REST tests for src/api/knowledge.py (Phase 6.4 — knowledge routes).

Requires PG. Monkey-patches `src.rag.ingest.embed` to return zero vectors
so the test does not hit any external embedding API — it still exercises
parse → chunk → DB insert end-to-end.

Run: python scripts/test_rest_knowledge.py
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import time
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
from src.api.knowledge import router as knowledge_router
from src.db import get_db
from src.files.manager import UPLOADS_DIR
from src.jobs import get_registry
from src.jobs.registry import reset_registry
from src.models import Document, DocumentChunk, Project
import src.rag.ingest as ingest_mod


# ── Test runner ────────────────────────────────────────────

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


# ── Fixtures ───────────────────────────────────────────────

PROJECT_ID = 1


async def _ensure_project() -> None:
    async with get_db() as db:
        existing = await db.get(Project, PROJECT_ID)
        if existing is not None:
            return
        await db.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, status) "
                "VALUES (:id, 1, 'rest-know-test', 'blog_generation', 'active')"
            ),
            {"id": PROJECT_ID},
        )


async def _cleanup() -> None:
    async with get_db() as db:
        # Delete chunks then documents. FK cascade may or may not apply.
        doc_ids_r = await db.execute(
            text("SELECT id FROM documents WHERE project_id = :p"),
            {"p": PROJECT_ID},
        )
        doc_ids = [r[0] for r in doc_ids_r.all()]
        if doc_ids:
            await db.execute(
                delete(DocumentChunk).where(DocumentChunk.doc_id.in_(doc_ids))
            )
        await db.execute(
            delete(Document).where(Document.project_id == PROJECT_ID)
        )
    proj_dir = UPLOADS_DIR / str(PROJECT_ID)
    if proj_dir.exists():
        for f in proj_dir.rglob("*"):
            if f.is_file():
                try:
                    f.unlink()
                except OSError:
                    pass


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(files_router)
    app.include_router(knowledge_router)
    return app


async def _fake_embed(texts, *, progress_callback=None):
    """Return zero-vectors of dim 1536; forward progress for realism."""
    total = len(texts)
    if progress_callback is not None:
        # Single tick covering the whole batch.
        await progress_callback(
            {"event": "embedding_progress", "done": total, "total": total}
        )
    return [[0.0] * 1536 for _ in texts]


# ── Tests ──────────────────────────────────────────────────


def run_tests(client: TestClient) -> None:
    # Upload a small markdown file via the files endpoint
    content = (
        "# Knowledge Test\n\n"
        + ("This is a paragraph with enough text to generate at least one chunk. " * 20)
    ).encode("utf-8")
    r = client.post(
        f"/projects/{PROJECT_ID}/files",
        files={"file": ("doc.md", content, "text/markdown")},
    )
    assert r.status_code == 200, r.text
    file_id = r.json()["id"]

    # ── Status before ingest ──
    section("knowledge status before ingest")
    r = client.get(f"/projects/{PROJECT_ID}/knowledge/status")
    check("status → 200", r.status_code == 200)
    body = r.json()
    check("file_count = 1", body.get("file_count") == 1)
    check("parsed_count = 0", body.get("parsed_count") == 0)
    check("total_chunks = 0", body.get("total_chunks") == 0)

    # ── Ingest + poll job ──
    section("POST ingest kicks off job")
    r = client.post(f"/projects/{PROJECT_ID}/files/{file_id}/ingest")
    check("ingest → 202", r.status_code == 202, r.text)
    job_id = r.json().get("job_id")
    check("job_id present", bool(job_id))

    # Poll the registry directly (no jobs REST yet — that's §6)
    deadline = time.time() + 15
    job = None
    while time.time() < deadline:
        job = get_registry().get(job_id)
        if job is not None and job.status in ("done", "failed"):
            break
        time.sleep(0.1)

    check("job reached terminal state", job is not None and job.status in ("done", "failed"), str(job.status if job else None))
    check("job status = done", job.status == "done", f"error={job.error!r}")

    # ── Chunks paginated ──
    section("GET chunks paginated")
    r = client.get(
        f"/projects/{PROJECT_ID}/files/{file_id}/chunks?offset=0&limit=5"
    )
    check("chunks → 200", r.status_code == 200)
    body = r.json()
    total = body.get("total", 0)
    check("total > 0", total > 0, str(total))
    check("items count ≤ 5", len(body.get("items", [])) <= 5)
    check("offset echoed", body.get("offset") == 0)
    check("limit echoed", body.get("limit") == 5)
    if body.get("items"):
        first = body["items"][0]
        check("chunk_index = 0 for first item", first.get("chunk_index") == 0)
        check("content is non-empty", bool(first.get("content")))

    # Second page
    r = client.get(
        f"/projects/{PROJECT_ID}/files/{file_id}/chunks?offset=1&limit=2"
    )
    body2 = r.json()
    check("page 2 total matches", body2.get("total") == total)
    if body2.get("items"):
        check(
            "page 2 first chunk_index = 1",
            body2["items"][0].get("chunk_index") == 1,
        )

    # ── Validation: limit out of range ──
    section("chunks validation")
    r = client.get(
        f"/projects/{PROJECT_ID}/files/{file_id}/chunks?limit=200"
    )
    check("limit=200 → 422", r.status_code == 422)

    r = client.get(
        f"/projects/{PROJECT_ID}/files/{file_id}/chunks?offset=-1"
    )
    check("offset=-1 → 422", r.status_code == 422)

    # ── Chunks for missing file ──
    r = client.get(f"/projects/{PROJECT_ID}/files/9999999/chunks")
    check("missing file chunks → 404", r.status_code == 404)

    # ── Ingest for missing file ──
    r = client.post(f"/projects/{PROJECT_ID}/files/9999999/ingest")
    check("missing file ingest → 404", r.status_code == 404)

    # ── Status after ingest ──
    section("knowledge status after ingest")
    r = client.get(f"/projects/{PROJECT_ID}/knowledge/status")
    body = r.json()
    check("file_count = 1", body.get("file_count") == 1)
    check("parsed_count = 1", body.get("parsed_count") == 1)
    check("total_chunks = chunks total", body.get("total_chunks") == total)


def main():
    reset_registry()
    asyncio.run(_ensure_project())
    asyncio.run(_cleanup())

    with patch("src.api.auth.get_settings") as gs, \
         patch.object(ingest_mod, "embed", new=_fake_embed):
        gs.return_value.api_keys = []
        app = _build_app()
        with TestClient(app) as client:
            try:
                run_tests(client)
            finally:
                try:
                    asyncio.run(_cleanup())
                except Exception as exc:
                    print(f"  [WARN] cleanup failed: {exc}")

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("All checks passed!")


if __name__ == "__main__":
    main()
