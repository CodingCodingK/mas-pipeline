"""Task manager: DAG-based task lifecycle with row-level locking for claiming."""

from __future__ import annotations

from sqlalchemy import func, select

from src.db import get_db
from src.models import Task


class AlreadyClaimedError(Exception):
    """Raised when trying to claim a task that is not pending."""


async def create_task(
    run_id: int,
    subject: str,
    description: str | None = None,
    blocked_by: list[int] | None = None,
) -> Task:
    """Create a new task in pending state."""
    task = Task(
        run_id=run_id,
        subject=subject,
        description=description,
        blocked_by=blocked_by or [],
    )
    async with get_db() as session:
        session.add(task)
        await session.flush()

    return task


async def list_tasks(run_id: int) -> list[Task]:
    """List all tasks for a pipeline run."""
    async with get_db() as session:
        result = await session.execute(
            select(Task).where(Task.run_id == run_id).order_by(Task.id)
        )
        return list(result.scalars().all())


async def get_task(task_id: int) -> Task | None:
    """Get a single task by id."""
    async with get_db() as session:
        return await session.get(Task, task_id)


async def claim_task(task_id: int, agent_id: str) -> Task:
    """Atomically claim a pending task using SELECT FOR UPDATE.

    Raises AlreadyClaimedError if the task is not in 'pending' status.
    """
    async with get_db() as session:
        result = await session.execute(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        task = result.scalars().first()

        if task is None:
            raise ValueError(f"Task {task_id} not found")

        if task.status != "pending":
            raise AlreadyClaimedError(
                f"Task {task_id} is '{task.status}', cannot claim"
            )

        task.status = "in_progress"
        task.owner = agent_id
        task.updated_at = func.now()

    return task


async def complete_task(task_id: int, result: str) -> Task:
    """Mark a task as completed with its output."""
    async with get_db() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        task.status = "completed"
        task.result = result
        task.updated_at = func.now()

    return task


async def fail_task(task_id: int, error: str) -> Task:
    """Mark a task as failed with error information."""
    async with get_db() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        task.status = "failed"
        task.result = error
        task.updated_at = func.now()

    return task


async def check_blocked(task_id: int) -> bool:
    """Check if a task's dependencies are all completed.

    Returns True if still blocked, False if all dependencies are met.
    A task with no dependencies is never blocked.
    """
    async with get_db() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        if not task.blocked_by:
            return False

        result = await session.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.id.in_(task.blocked_by), Task.status != "completed")
        )
        incomplete_count = result.scalar()

    return incomplete_count > 0
