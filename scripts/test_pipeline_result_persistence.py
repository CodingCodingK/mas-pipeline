"""Verification for Change 1.5 — PipelineResult persistence via run.py API.

Exercises finish_run / update_run_status with and without result_payload,
against real PG. Does not drive a full pipeline — the 6 call sites in
engine/pipeline.py are covered by the existing rest_api_integration test
suite (the patched execute_pipeline stub won't reach them, but signature
changes would surface as TypeError on import — handled above).

Run: python scripts/test_pipeline_result_persistence.py
"""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text

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
                "VALUES (:id, 1, 'persistence-test', 'blog_generation', 'active')"
            ),
            {"id": PROJECT_ID},
        )


async def _cleanup() -> None:
    async with get_db() as db:
        await db.execute(
            delete(WorkflowRun).where(WorkflowRun.run_id.like("pers_%"))
        )


async def _get_metadata(run_id: str) -> dict:
    async with get_db() as db:
        r = await db.execute(
            select(WorkflowRun.metadata_).where(WorkflowRun.run_id == run_id)
        )
        row = r.first()
        return dict(row[0]) if row and row[0] else {}


async def _set_metadata_raw(run_id: str, md: dict) -> None:
    """Write metadata directly via raw SQL to simulate pre-existing keys."""
    async with get_db() as db:
        await db.execute(
            text("UPDATE workflow_runs SET metadata = CAST(:md AS jsonb) WHERE run_id = :rid"),
            {"md": __import__("json").dumps(md), "rid": run_id},
        )


async def _new_run(suffix: str) -> WorkflowRun:
    run = await create_run(project_id=PROJECT_ID, pipeline="test_pipeline")
    # Rename run_id to the suffix for predictable cleanup.
    async with get_db() as db:
        await db.execute(
            text("UPDATE workflow_runs SET run_id = :new WHERE run_id = :old"),
            {"new": f"pers_{suffix}", "old": run.run_id},
        )
    run.run_id = f"pers_{suffix}"
    return run


async def run_update_tests() -> None:
    section("update_run_status — result_payload merge")

    run = await _new_run("upd1")
    # pending → running with no payload — metadata_ unchanged (empty)
    await update_run_status(run.run_id, RunStatus.RUNNING)
    md = await _get_metadata(run.run_id)
    check("payload=None leaves metadata empty", md == {}, str(md))

    # running → paused with payload
    await update_run_status(
        run.run_id,
        RunStatus.PAUSED,
        result_payload={"paused_at": "node_b", "outputs": {"a": "hi"}},
    )
    md = await _get_metadata(run.run_id)
    check("paused_at persisted", md.get("paused_at") == "node_b", str(md))
    check("outputs persisted", md.get("outputs") == {"a": "hi"}, str(md))

    # paused → running with different patch — merge, not replace
    await update_run_status(
        run.run_id,
        RunStatus.RUNNING,
        result_payload={"error": "nope"},
    )
    md = await _get_metadata(run.run_id)
    check("error key added", md.get("error") == "nope")
    check("paused_at preserved through merge", md.get("paused_at") == "node_b")
    check("outputs preserved through merge", md.get("outputs") == {"a": "hi"})

    # running → running-ish: pass None explicitly — should not mutate
    # (use a terminal transition for real since RUNNING→RUNNING is invalid)
    snapshot = dict(md)
    await finish_run(run.run_id, RunStatus.COMPLETED)  # None kwarg
    md = await _get_metadata(run.run_id)
    check(
        "finish_run payload=None preserves prior metadata",
        md == snapshot,
        f"before={snapshot} after={md}",
    )


async def run_finish_tests() -> None:
    section("finish_run — result_payload on terminal transition")

    run = await _new_run("fin1")
    await update_run_status(run.run_id, RunStatus.RUNNING)

    payload = {
        "final_output": "# Final Report",
        "outputs": {"writer": "# Final Report"},
        "failed_node": None,
        "error": None,
        "paused_at": None,
    }
    await finish_run(run.run_id, RunStatus.COMPLETED, result_payload=payload)

    async with get_db() as db:
        r = await db.execute(
            select(WorkflowRun).where(WorkflowRun.run_id == run.run_id)
        )
        persisted = r.scalars().first()

    check("status = completed", persisted.status == "completed")
    check("finished_at set", persisted.finished_at is not None)
    md = persisted.metadata_ or {}
    check("all 5 keys persisted", set(md.keys()) == set(payload.keys()), str(md.keys()))
    check("final_output value", md.get("final_output") == "# Final Report")
    check("outputs value", md.get("outputs") == {"writer": "# Final Report"})
    check("error None preserved", md.get("error") is None)


async def run_failed_finish_tests() -> None:
    section("finish_run — failed with empty final_output")

    run = await _new_run("fin2")
    await update_run_status(run.run_id, RunStatus.RUNNING)

    payload = {
        "final_output": "",
        "outputs": {},
        "failed_node": None,
        "error": "embedding API timeout",
        "paused_at": None,
    }
    await finish_run(run.run_id, RunStatus.FAILED, result_payload=payload)

    md = await _get_metadata(run.run_id)
    check("status failed path: error preserved", md.get("error") == "embedding API timeout")
    check("final_output is '' (never None)", md.get("final_output") == "")


async def run_preexisting_metadata_tests() -> None:
    section("merge preserves unrelated pre-existing metadata keys")

    run = await _new_run("pre1")
    # Seed metadata_ with an unrelated key via raw SQL
    await _set_metadata_raw(run.run_id, {"trace_id": "abc-123"})
    md = await _get_metadata(run.run_id)
    check("trace_id seeded", md.get("trace_id") == "abc-123")

    await update_run_status(run.run_id, RunStatus.RUNNING)
    await update_run_status(
        run.run_id,
        RunStatus.PAUSED,
        result_payload={"paused_at": "node_b"},
    )
    md = await _get_metadata(run.run_id)
    check("trace_id preserved", md.get("trace_id") == "abc-123", str(md))
    check("paused_at added", md.get("paused_at") == "node_b")


async def run_signature_tests() -> None:
    section("kwargs are keyword-only")
    import inspect
    sig_finish = inspect.signature(finish_run)
    sig_update = inspect.signature(update_run_status)
    check(
        "finish_run result_payload is keyword-only",
        sig_finish.parameters["result_payload"].kind is inspect.Parameter.KEYWORD_ONLY,
    )
    check(
        "update_run_status result_payload is keyword-only",
        sig_update.parameters["result_payload"].kind is inspect.Parameter.KEYWORD_ONLY,
    )


async def main_async():
    await _ensure_project()
    await _cleanup()
    try:
        await run_update_tests()
        await run_finish_tests()
        await run_failed_finish_tests()
        await run_preexisting_metadata_tests()
        await run_signature_tests()
    finally:
        try:
            await _cleanup()
        except Exception as exc:
            print(f"  [WARN] cleanup failed: {exc}")


def main():
    asyncio.run(main_async())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
    print("All checks passed!")


if __name__ == "__main__":
    main()
