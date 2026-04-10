"""Phase 6.1 §9.2 — pipeline StreamEvent fan-out via in-process registry.

Two layers of test:

1. **Registry primitives** (no PG, no app): subscribe / emit / fan-out / drop /
   unsubscribe / multi-subscriber semantics.

2. **End-to-end via the trigger endpoint** (real PG, mocked execute_pipeline):
   POST .../runs?stream=true subscribes to the queue, our patched
   execute_pipeline calls `emit_pipeline_event` directly to simulate the
   real engine. We verify the SSE response carries the events through.

The end-to-end test uses httpx.AsyncClient + ASGITransport because for a
*finite* event stream (which terminates with `pipeline_end`), the transport
*does* return — it only deadlocks on infinite SSE generators.

Run: python scripts/test_pipeline_event_stream.py
"""
from __future__ import annotations

import asyncio
import json
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, text

from src.db import get_db
from src.engine.run import (
    _pipeline_event_streams,
    emit_pipeline_event,
    subscribe_pipeline_events,
    unsubscribe_pipeline_events,
)
from src.models import Project, WorkflowRun

passed = 0
failed = 0


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


# ── Registry primitive tests ─────────────────────────────────


def _reset_registry() -> None:
    _pipeline_event_streams.clear()


async def test_subscribe_emit_drain():
    print("\n=== subscribe → emit → drain ===")
    _reset_registry()

    q = subscribe_pipeline_events("run-A")
    emit_pipeline_event("run-A", {"type": "node_start", "node": "n1"})
    emit_pipeline_event("run-A", {"type": "node_end", "node": "n1"})

    check("queue has 2 events", q.qsize() == 2)
    e1 = await asyncio.wait_for(q.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q.get(), timeout=1.0)
    check("first event is node_start", e1.get("type") == "node_start")
    check("second event is node_end", e2.get("type") == "node_end")


async def test_emit_with_no_subscribers_is_noop():
    print("\n=== emit with zero subscribers does nothing ===")
    _reset_registry()
    # Should not raise, should not allocate anything.
    emit_pipeline_event("nobody", {"type": "x"})
    check("no entry created in registry",
          "nobody" not in _pipeline_event_streams)


async def test_multi_subscriber_fanout():
    print("\n=== multi-subscriber fan-out ===")
    _reset_registry()
    q1 = subscribe_pipeline_events("run-B")
    q2 = subscribe_pipeline_events("run-B")
    emit_pipeline_event("run-B", {"type": "pipeline_start"})

    check("subscriber 1 received", q1.qsize() == 1)
    check("subscriber 2 received", q2.qsize() == 1)
    check("registry has 2 subs", len(_pipeline_event_streams["run-B"]) == 2)


async def test_unsubscribe_cleans_up():
    print("\n=== unsubscribe removes queue + collapses entry ===")
    _reset_registry()
    q = subscribe_pipeline_events("run-C")
    check("entry created", "run-C" in _pipeline_event_streams)
    unsubscribe_pipeline_events("run-C", q)
    check("entry removed when last sub leaves",
          "run-C" not in _pipeline_event_streams)
    # Idempotent
    unsubscribe_pipeline_events("run-C", q)
    check("unsubscribe is idempotent",
          "run-C" not in _pipeline_event_streams)


async def test_emit_isolates_per_run():
    print("\n=== events for run-X don't leak to run-Y ===")
    _reset_registry()
    qx = subscribe_pipeline_events("run-X")
    qy = subscribe_pipeline_events("run-Y")
    emit_pipeline_event("run-X", {"type": "marker"})

    check("X received", qx.qsize() == 1)
    check("Y did not receive", qy.qsize() == 0)


async def test_full_queue_drops_silently():
    print("\n=== full queue drops without raising ===")
    _reset_registry()
    q = subscribe_pipeline_events("run-D")
    # Blow past the cap (200) — should not raise.
    for i in range(250):
        emit_pipeline_event("run-D", {"type": "spam", "i": i})
    check("queue capped near limit", q.qsize() <= 200)
    check("emit never raised on overflow", True)


async def test_emit_after_unsubscribe_is_noop():
    print("\n=== emit after unsubscribe is no-op ===")
    _reset_registry()
    q = subscribe_pipeline_events("run-E")
    unsubscribe_pipeline_events("run-E", q)
    emit_pipeline_event("run-E", {"type": "late"})
    check("no leftover entries", "run-E" not in _pipeline_event_streams)


# ── End-to-end via trigger endpoint ──────────────────────────


async def _ensure_project(project_id: int = 1) -> None:
    async with get_db() as db:
        existing = await db.get(Project, project_id)
        if existing is not None:
            return
        await db.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, status) "
                "VALUES (:id, 1, 'pipeline-event-test', 'blog_generation', 'active')"
            ),
            {"id": project_id},
        )


async def _cleanup_runs() -> None:
    async with get_db() as db:
        await db.execute(
            delete(WorkflowRun).where(WorkflowRun.pipeline == "blog_generation").where(
                WorkflowRun.status.in_(("pending", "running", "completed", "failed"))
            )
        )


async def test_endpoint_streams_emitted_events():
    print("\n=== POST .../runs?stream=true streams emitted events ===")

    import importlib
    import httpx
    import src.main as main_module
    importlib.reload(main_module)
    app = main_module.app

    # Patch execute_pipeline to manually emit a sequence of events instead of
    # actually running a pipeline. This isolates the API → registry → SSE path.
    async def fake_execute(pipeline_name, run_id, project_id, user_input, **kwargs):
        # Tiny sleeps so the SSE consumer has a chance to drain incrementally.
        emit_pipeline_event(run_id, {"type": "pipeline_start", "pipeline": pipeline_name})
        await asyncio.sleep(0.02)
        emit_pipeline_event(run_id, {"type": "node_start", "node": "writer"})
        await asyncio.sleep(0.02)
        emit_pipeline_event(run_id, {"type": "node_end", "node": "writer", "output_length": 42})
        await asyncio.sleep(0.02)
        emit_pipeline_event(run_id, {"type": "pipeline_end", "status": "completed"})

    async with app.router.lifespan_context(app):
        with patch("src.api.auth.get_settings") as auth_settings, patch(
            "src.api.runs.execute_pipeline", new=AsyncMock(side_effect=fake_execute)
        ):
            auth_settings.return_value.api_keys = []

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                received: list[dict] = []
                received_event_types: list[str] = []

                async with ac.stream(
                    "POST",
                    "/api/projects/1/pipelines/blog_generation/runs?stream=true",
                    json={"input": {"topic": "Redis"}},
                    timeout=15.0,
                ) as response:
                    check("status 200", response.status_code == 200,
                          str(response.status_code))
                    check(
                        "content-type event-stream",
                        "text/event-stream" in response.headers.get("content-type", ""),
                    )
                    buffer = ""
                    cur: dict = {}
                    async for chunk in response.aiter_bytes():
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.rstrip("\r")
                            if not line:
                                if cur:
                                    received.append(cur)
                                    if "event" in cur:
                                        received_event_types.append(cur["event"])
                                    cur = {}
                                continue
                            if line.startswith("event:"):
                                cur["event"] = line.split(":", 1)[1].strip()
                            elif line.startswith("data:"):
                                cur["data"] = line.split(":", 1)[1].strip()

    check(
        "received pipeline_start event",
        "pipeline_start" in received_event_types,
        str(received_event_types),
    )
    check(
        "received node_start event",
        "node_start" in received_event_types,
    )
    check(
        "received node_end event",
        "node_end" in received_event_types,
    )
    check(
        "received pipeline_end event",
        "pipeline_end" in received_event_types,
    )
    check(
        "stream terminates on pipeline_end",
        received_event_types[-1] == "pipeline_end",
        str(received_event_types),
    )

    # Decode payloads of node_end and verify field passthrough
    for r in received:
        if r.get("event") == "node_end":
            data = json.loads(r["data"])
            check("node_end has output_length field",
                  data.get("output_length") == 42)
            check("node_end has run_id injected",
                  "run_id" in data)
            break


# ── Main ─────────────────────────────────────────────────────


async def main():
    # Registry primitives
    await test_subscribe_emit_drain()
    await test_emit_with_no_subscribers_is_noop()
    await test_multi_subscriber_fanout()
    await test_unsubscribe_cleans_up()
    await test_emit_isolates_per_run()
    await test_full_queue_drops_silently()
    await test_emit_after_unsubscribe_is_noop()

    # End-to-end
    await _ensure_project(1)
    try:
        await test_endpoint_streams_emitted_events()
    finally:
        try:
            await _cleanup_runs()
        except Exception as exc:
            print(f"  [WARN] cleanup failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
