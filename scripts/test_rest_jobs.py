"""REST tests for src/api/jobs.py (Phase 6.4 — job status + SSE stream).

No PG required: operates entirely on the in-memory JobRegistry.

Run: python scripts/test_rest_jobs.py
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from pathlib import Path
from unittest.mock import patch

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI

from src.api.jobs import router as jobs_router
from src.jobs import get_registry
from src.jobs.registry import reset_registry


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


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(jobs_router)
    return app


# ── Tests ──────────────────────────────────────────────────


def run_get_job_tests() -> None:
    from fastapi.testclient import TestClient

    section("GET /jobs/:id")

    reset_registry()
    app = _build_app()

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []

        job = get_registry().create(kind="ingest")
        job.emit({"event": "parsing_started"})
        job.emit({"event": "parsing_done", "text_length": 500})

        with TestClient(app) as client:
            r = client.get(f"/jobs/{job.id}")
            check("GET existing job → 200", r.status_code == 200)
            body = r.json()
            check("id matches", body.get("id") == job.id)
            check("kind = ingest", body.get("kind") == "ingest")
            check("status = running", body.get("status") == "running")
            check(
                "last_event is parsing_done",
                (body.get("last_event") or {}).get("event") == "parsing_done",
            )

            r = client.get("/jobs/nonexistent")
            check("missing job → 404", r.status_code == 404)


def run_get_job_auth_test() -> None:
    from fastapi.testclient import TestClient

    section("GET /jobs/:id auth")

    reset_registry()
    app = _build_app()

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = ["secret"]
        job = get_registry().create(kind="ingest")

        with TestClient(app) as client:
            r = client.get(f"/jobs/{job.id}")
            check("missing key → 401", r.status_code == 401)
            r = client.get(
                f"/jobs/{job.id}", headers={"X-API-Key": "secret"}
            )
            check("valid key → 200", r.status_code == 200)


async def _collect_sse(app, job_id: str, *, timeout: float = 5.0) -> tuple[int, list[dict]]:
    """Drive the SSE endpoint via httpx ASGITransport inside the event loop
    the job's asyncio.Queue lives in. Returns (status_code, events)."""
    import httpx

    events: list[dict] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        async with ac.stream(
            "GET", f"/jobs/{job_id}/stream", timeout=timeout
        ) as response:
            status = response.status_code
            if status != 200:
                return status, events
            buffer = ""
            try:
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    buffer += chunk.decode("utf-8", errors="replace")
                    # Parse complete SSE frames (terminated by blank line)
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        data_line = next(
                            (l for l in frame.splitlines() if l.startswith("data:")),
                            None,
                        )
                        event_line = next(
                            (l for l in frame.splitlines() if l.startswith("event:")),
                            None,
                        )
                        if data_line is None:
                            continue
                        try:
                            payload = json.loads(data_line.split(":", 1)[1].strip())
                        except json.JSONDecodeError:
                            continue
                        ev_type = (
                            event_line.split(":", 1)[1].strip()
                            if event_line
                            else "message"
                        )
                        events.append({"_sse_event": ev_type, **payload})
                        if payload.get("event") in ("done", "failed"):
                            return status, events
            except (httpx.ReadTimeout, asyncio.TimeoutError):
                pass
    return status, events


async def _sse_live_stream_test() -> None:
    section("SSE stream: live job emits ordered progress + done")

    reset_registry()
    app = _build_app()

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        job = get_registry().create(kind="ingest")

        async def _driver():
            # Small delay so the stream is reading the queue before we emit.
            await asyncio.sleep(0.05)
            job.emit({"event": "parsing_started"})
            await asyncio.sleep(0.01)
            job.emit({"event": "parsing_done", "text_length": 100})
            await asyncio.sleep(0.01)
            job.emit({"event": "embedding_progress", "done": 5, "total": 10})
            await asyncio.sleep(0.01)
            job.emit({"event": "embedding_progress", "done": 10, "total": 10})
            await asyncio.sleep(0.01)
            job.emit({"event": "done", "chunks": 10})

        driver_task = asyncio.create_task(_driver())
        status, events = await _collect_sse(app, job.id, timeout=5.0)
        await driver_task

    check("stream 200", status == 200, str(status))
    kinds = [e.get("event") for e in events]
    check(
        "received 5 progress events",
        len(events) == 5,
        f"got {len(events)}: {kinds}",
    )
    check(
        "first event parsing_started",
        events and events[0].get("event") == "parsing_started",
    )
    check(
        "last event done",
        events and events[-1].get("event") == "done",
    )
    check(
        "done chunks=10",
        events and events[-1].get("chunks") == 10,
    )
    check(
        "all frames are SSE event=progress",
        all(e.get("_sse_event") == "progress" for e in events),
    )


async def _sse_finished_job_replay_test() -> None:
    section("SSE stream: already-finished job replays last_event")

    reset_registry()
    app = _build_app()

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        job = get_registry().create(kind="ingest")
        # Drive it to done before any client connects.
        job.emit({"event": "parsing_started"})
        job.emit({"event": "done", "chunks": 42})
        assert job.status == "done"

        status, events = await _collect_sse(app, job.id, timeout=3.0)

    check("stream 200", status == 200)
    check("got exactly 1 replay event", len(events) == 1, str(len(events)))
    if events:
        check("replay event is done", events[0].get("event") == "done")
        check("replay chunks=42", events[0].get("chunks") == 42)


async def _sse_failed_job_replay_test() -> None:
    section("SSE stream: failed job replays failed event")

    reset_registry()
    app = _build_app()

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        job = get_registry().create(kind="ingest")
        job.emit({"event": "failed", "error": "boom"})

        status, events = await _collect_sse(app, job.id, timeout=3.0)

    check("stream 200", status == 200)
    check("got 1 replay event", len(events) == 1)
    if events:
        check("event=failed", events[0].get("event") == "failed")
        check("error=boom", events[0].get("error") == "boom")


async def _sse_missing_job_test() -> None:
    section("SSE stream: missing job → 404")

    reset_registry()
    app = _build_app()

    with patch("src.api.auth.get_settings") as gs:
        gs.return_value.api_keys = []
        status, events = await _collect_sse(app, "nonexistent", timeout=2.0)
    check("stream 404", status == 404, str(status))


def main():
    run_get_job_tests()
    run_get_job_auth_test()

    async def _async_tests():
        await _sse_live_stream_test()
        await _sse_finished_job_replay_test()
        await _sse_failed_job_replay_test()
        await _sse_missing_job_test()

    asyncio.run(_async_tests())

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("All checks passed!")


if __name__ == "__main__":
    main()
