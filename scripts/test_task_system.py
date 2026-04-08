"""Verification for task system: create, claim, complete, fail, DAG dependency check."""

import asyncio
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import Task
from src.task.manager import (
    AlreadyClaimedError,
    check_blocked,
    claim_task,
    complete_task,
    create_task,
    fail_task,
    get_task,
    list_tasks,
)

# We need a workflow_run record for the FK. Create one in setup.
TEST_RUN_ID = None


async def setup_test_run() -> int:
    """Insert a minimal workflow_run record for FK satisfaction."""
    from src.project.manager import create_project

    project = await create_project(user_id=1, name="Task Test Project", pipeline="test")

    from sqlalchemy import text

    from src.db import get_db

    async with get_db() as session:
        result = await session.execute(
            text(
                "INSERT INTO workflow_runs (project_id, run_id, pipeline, status) "
                "VALUES (:pid, :rid, 'test', 'pending') RETURNING id"
            ),
            {"pid": project.id, "rid": f"run-task-test-{project.id}"},
        )
        row = result.first()
        return row[0]


async def test_create_task(run_id: int):
    print("=== create_task ===")
    task = await create_task(run_id, subject="Research topic", description="Find sources")

    assert isinstance(task, Task)
    assert task.id > 0
    assert task.status == "pending"
    assert task.blocked_by == []
    assert task.owner is None
    print(f"  created: id={task.id}, subject={task.subject}, status={task.status}")
    print("  OK")
    return task


async def test_create_task_with_deps(run_id: int, blocked_by: list[int]):
    print("=== create_task: with dependencies ===")
    task = await create_task(
        run_id, subject="Write draft", description="Based on research", blocked_by=blocked_by
    )

    assert task.blocked_by == blocked_by
    print(f"  created: id={task.id}, blocked_by={task.blocked_by}")
    print("  OK")
    return task


async def test_claim_task(task_id: int):
    print("=== claim_task ===")
    task = await claim_task(task_id, agent_id="researcher-001")

    assert task.status == "in_progress"
    assert task.owner == "researcher-001"
    print(f"  claimed: id={task.id}, owner={task.owner}, status={task.status}")

    # Double claim should fail
    try:
        await claim_task(task_id, agent_id="researcher-002")
        print("  FAIL: expected AlreadyClaimedError")
    except AlreadyClaimedError as e:
        print(f"  double claim rejected: {e}")

    print("  OK")


async def test_complete_task(task_id: int):
    print("=== complete_task ===")
    task = await complete_task(task_id, result="Found 5 relevant sources on topic X")

    assert task.status == "completed"
    assert "5 relevant sources" in task.result
    print(f"  completed: id={task.id}, result={task.result[:50]}")
    print("  OK")


async def test_fail_task(run_id: int):
    print("=== fail_task ===")
    task = await create_task(run_id, subject="Will fail")
    await claim_task(task.id, agent_id="agent-fail")
    task = await fail_task(task.id, error="LLM returned error: rate limited")

    assert task.status == "failed"
    assert "rate limited" in task.result
    print(f"  failed: id={task.id}, result={task.result}")
    print("  OK")


async def test_check_blocked(completed_id: int, writer_id: int):
    print("=== check_blocked ===")

    # writer blocked by researcher (which is now completed)
    blocked = await check_blocked(writer_id)
    assert blocked is False, f"Expected not blocked (dep completed), got {blocked}"
    print(f"  task {writer_id} blocked_by=[{completed_id}] (completed) -> not blocked: OK")

    # Create a task blocked by a pending task
    task_pending = await create_task(
        (await get_task(writer_id)).run_id, subject="Pending dep task"
    )
    task_blocked = await create_task(
        task_pending.run_id, subject="Blocked task", blocked_by=[task_pending.id]
    )
    blocked = await check_blocked(task_blocked.id)
    assert blocked is True, f"Expected blocked (dep pending), got {blocked}"
    print(f"  task {task_blocked.id} blocked_by=[{task_pending.id}] (pending) -> blocked: OK")

    # Task with no deps
    task_free = await create_task(task_pending.run_id, subject="Free task")
    blocked = await check_blocked(task_free.id)
    assert blocked is False
    print(f"  task {task_free.id} blocked_by=[] -> not blocked: OK")

    print("  OK")


async def test_list_and_get(run_id: int):
    print("=== list_tasks / get_task ===")
    tasks = await list_tasks(run_id)

    assert len(tasks) > 0
    print(f"  list_tasks: {len(tasks)} task(s)")

    task = await get_task(tasks[0].id)
    assert task is not None
    assert task.id == tasks[0].id
    print(f"  get_task({task.id}): subject={task.subject}")

    none_task = await get_task(99999)
    assert none_task is None
    print("  get_task(99999) -> None: OK")

    print("  OK")


async def main():
    print("\n--- Task System Verification ---\n")

    from src.db import close_db, init_db

    await init_db()

    try:
        run_id = await setup_test_run()
        print(f"Test run_id: {run_id}\n")

        researcher = await test_create_task(run_id)
        writer = await test_create_task_with_deps(run_id, blocked_by=[researcher.id])
        await test_claim_task(researcher.id)
        await test_complete_task(researcher.id)
        await test_fail_task(run_id)
        await test_check_blocked(researcher.id, writer.id)
        await test_list_and_get(run_id)
    finally:
        await close_db()

    print("\n[PASS] All task system tests passed!\n")


if __name__ == "__main__":
    # Windows: psycopg requires SelectorEventLoop
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
