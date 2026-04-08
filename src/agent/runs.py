"""AgentRun: audit records for sub-agent executions.

Pure write-only records — system control flow does NOT depend on these.
Control flow is driven by asyncio.Queue notifications.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.db import get_db
from src.models import AgentRun


async def create_agent_run(
    run_id: int,
    role: str,
    description: str | None = None,
    *,
    owner: str | None = None,
) -> AgentRun:
    """Record that a sub-agent has been launched."""
    agent_run = AgentRun(
        run_id=run_id,
        role=role,
        description=description,
        status="running",
        owner=owner,
    )
    async with get_db() as session:
        session.add(agent_run)
        await session.flush()

    return agent_run


async def complete_agent_run(agent_run_id: int, result: str) -> AgentRun:
    """Record that a sub-agent completed successfully."""
    async with get_db() as session:
        agent_run = await session.get(AgentRun, agent_run_id)
        if agent_run is None:
            raise ValueError(f"AgentRun {agent_run_id} not found")

        agent_run.status = "completed"
        agent_run.result = result
        agent_run.updated_at = func.now()

    return agent_run


async def fail_agent_run(agent_run_id: int, error: str) -> AgentRun:
    """Record that a sub-agent failed."""
    async with get_db() as session:
        agent_run = await session.get(AgentRun, agent_run_id)
        if agent_run is None:
            raise ValueError(f"AgentRun {agent_run_id} not found")

        agent_run.status = "failed"
        agent_run.result = error
        agent_run.updated_at = func.now()

    return agent_run


async def list_agent_runs(run_id: int) -> list[AgentRun]:
    """List all agent runs for a workflow run."""
    async with get_db() as session:
        result = await session.execute(
            select(AgentRun).where(AgentRun.run_id == run_id).order_by(AgentRun.id)
        )
        return list(result.scalars().all())


async def get_agent_run(agent_run_id: int) -> AgentRun | None:
    """Get a single agent run by id."""
    async with get_db() as session:
        return await session.get(AgentRun, agent_run_id)
