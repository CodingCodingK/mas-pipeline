"""Verification for Phase 2.6 Workflow Run management.

Tests:
1. RunStatus enum + state machine transitions
2. create_run with extended parameters + Redis sync
3. get_run / list_runs
4. update_run_status with state machine validation
5. finish_run with terminal state + finished_at
6. InvalidTransitionError on illegal transitions
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS_COUNT = 0


def check(label, condition, detail=""):
    global PASS_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"  [PASS] {label}", flush=True)
    else:
        print(f"  [FAIL] {label} — {detail}", flush=True)
        raise AssertionError(f"{label}: {detail}")


async def ensure_test_data():
    from sqlalchemy import text

    from src.db import get_db

    async with get_db() as session:
        r = await session.execute(text("SELECT id FROM users WHERE id=1"))
        if r.scalar() is None:
            await session.execute(
                text("INSERT INTO users (id, name, email) VALUES (1, 'test', 'test@test.com')")
            )
        r = await session.execute(text("SELECT id FROM projects WHERE id=1"))
        if r.scalar() is None:
            await session.execute(
                text(
                    "INSERT INTO projects (id, user_id, name, pipeline)"
                    " VALUES (1, 1, 'test', 'test')"
                )
            )


async def test_state_machine():
    print("\n=== 1. RunStatus + state machine ===", flush=True)
    from src.engine.run import InvalidTransitionError, RunStatus, _validate_transition

    # Valid transitions
    _validate_transition("pending", RunStatus.RUNNING)
    check("pending → running", True)

    _validate_transition("running", RunStatus.COMPLETED)
    check("running → completed", True)

    _validate_transition("running", RunStatus.FAILED)
    check("running → failed", True)

    # Invalid transitions
    try:
        _validate_transition("completed", RunStatus.RUNNING)
        check("completed → running rejected", False)
    except InvalidTransitionError:
        check("completed → running rejected", True)

    try:
        _validate_transition("pending", RunStatus.COMPLETED)
        check("pending → completed rejected", False)
    except InvalidTransitionError:
        check("pending → completed rejected", True)

    try:
        _validate_transition("failed", RunStatus.RUNNING)
        check("failed → running rejected", False)
    except InvalidTransitionError:
        check("failed → running rejected", True)


async def test_create_run():
    print("\n=== 2. create_run ===", flush=True)
    from src.db import get_redis
    from src.engine.run import create_run

    # Basic create
    run = await create_run(project_id=1)
    check("returns WorkflowRun", run is not None)
    check("has id", run.id > 0)
    check("has run_id", len(run.run_id) == 16)
    check("status is pending", run.status == "pending")
    check("started_at set", run.started_at is not None)
    check("session_id is None", run.session_id is None)
    check("pipeline is None", run.pipeline is None)
    print(f"    created: id={run.id}, run_id={run.run_id}", flush=True)

    # Create with all params
    run2 = await create_run(project_id=1, session_id=None, pipeline="blog_generation")
    check("pipeline set", run2.pipeline == "blog_generation")
    check("unique run_id", run.run_id != run2.run_id)

    # Redis sync
    redis = get_redis()
    data = await redis.hgetall(f"workflow_run:{run.run_id}")
    check("redis has data", len(data) > 0)
    check("redis status=pending", data.get("status") == "pending")
    check("redis project_id=1", data.get("project_id") == "1")
    print(f"    redis: {data}", flush=True)

    return run


async def test_get_and_list(run_id: str):
    print("\n=== 3. get_run / list_runs ===", flush=True)
    from src.engine.run import get_run, list_runs

    run = await get_run(run_id)
    check("get_run returns run", run is not None)
    check("correct run_id", run.run_id == run_id)

    none_run = await get_run("nonexistent_xyz")
    check("get_run returns None for missing", none_run is None)

    runs = await list_runs(project_id=1)
    check("list_runs returns list", len(runs) > 0)
    check("newest first", runs[0].id >= runs[-1].id)
    print(f"    list_runs: {len(runs)} run(s)", flush=True)


async def test_update_status(run_id: str):
    print("\n=== 4. update_run_status ===", flush=True)
    from src.db import get_redis
    from src.engine.run import InvalidTransitionError, RunStatus, update_run_status

    # pending → running
    run = await update_run_status(run_id, RunStatus.RUNNING)
    check("status updated to running", run.status == "running")

    # Redis synced
    redis = get_redis()
    data = await redis.hgetall(f"workflow_run:{run_id}")
    check("redis status=running", data.get("status") == "running")

    # Invalid: running → pending
    try:
        await update_run_status(run_id, RunStatus.PENDING)
        check("running → pending rejected", False)
    except InvalidTransitionError:
        check("running → pending rejected", True)

    # Not found
    try:
        await update_run_status("nonexistent_xyz", RunStatus.RUNNING)
        check("not found raises ValueError", False)
    except ValueError:
        check("not found raises ValueError", True)


async def test_finish_run(run_id: str):
    print("\n=== 5. finish_run ===", flush=True)
    from src.db import get_redis
    from src.engine.run import InvalidTransitionError, RunStatus, finish_run

    # running → completed
    run = await finish_run(run_id, RunStatus.COMPLETED)
    check("status=completed", run.status == "completed")
    check("finished_at set", run.finished_at is not None)
    print(f"    finished_at: {run.finished_at}", flush=True)

    # Redis synced
    redis = get_redis()
    data = await redis.hgetall(f"workflow_run:{run_id}")
    check("redis status=completed", data.get("status") == "completed")
    check("redis finished_at set", data.get("finished_at", "") != "")

    # Cannot transition from completed
    try:
        await finish_run(run_id, RunStatus.FAILED)
        check("completed → failed rejected", False)
    except InvalidTransitionError:
        check("completed → failed rejected", True)

    # Non-terminal status rejected
    try:
        from src.engine.run import create_run

        run2 = await create_run(project_id=1)
        await finish_run(run2.run_id, RunStatus.RUNNING)
        check("non-terminal rejected", False)
    except ValueError:
        check("non-terminal rejected", True)


async def test_finish_failed():
    print("\n=== 6. finish_run (failed path) ===", flush=True)
    from src.engine.run import RunStatus, create_run, finish_run, update_run_status

    run = await create_run(project_id=1)
    await update_run_status(run.run_id, RunStatus.RUNNING)
    run = await finish_run(run.run_id, RunStatus.FAILED)
    check("status=failed", run.status == "failed")
    check("finished_at set", run.finished_at is not None)


async def main():
    print("\n--- Phase 2.6 Workflow Run Verification ---", flush=True)

    from src.db import close_db, init_db

    await init_db()
    try:
        await ensure_test_data()

        await test_state_machine()
        run = await test_create_run()
        await test_get_and_list(run.run_id)
        await test_update_status(run.run_id)
        await test_finish_run(run.run_id)
        await test_finish_failed()
    finally:
        await close_db()

    print(f"\n[PASS] All {PASS_COUNT} checks passed!\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
