"""Pipeline run management: minimal create_run for Phase 2.5."""

from __future__ import annotations

import uuid

from sqlalchemy import func

from src.db import get_db
from src.models import PipelineRun


async def create_run(project_id: int) -> PipelineRun:
    """Create a minimal pipeline run record.

    Generates a unique run_id (UUID-based), sets status='running' and started_at=now().
    Full run management (update/list/get/Redis sync) deferred to Phase 2.6.
    """
    run = PipelineRun(
        project_id=project_id,
        run_id=uuid.uuid4().hex[:16],
        status="running",
        started_at=func.now(),
    )
    async with get_db() as session:
        session.add(run)
        await session.flush()

    return run
