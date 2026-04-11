"""JobRegistry: process-wide singleton for tracking active jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from src.jobs.job import Job

logger = logging.getLogger(__name__)


class JobRegistry:
    """In-memory registry of Jobs keyed by id."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, kind: str = "generic") -> Job:
        """Instantiate and store a new Job."""
        job = Job(kind=kind)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())

    async def cleanup_finished(self, max_age_sec: int = 86400) -> int:
        """Remove finished jobs whose finished_at is older than max_age_sec.

        Returns the count removed. Running/pending jobs are never removed.
        """
        now = datetime.now(timezone.utc)
        to_remove: list[str] = []
        for job in self._jobs.values():
            if job.status in ("done", "failed") and job.finished_at is not None:
                age = (now - job.finished_at).total_seconds()
                if age > max_age_sec:
                    to_remove.append(job.id)
        for jid in to_remove:
            del self._jobs[jid]
        if to_remove:
            logger.info("Cleaned up %d finished jobs older than %ds", len(to_remove), max_age_sec)
        return len(to_remove)


_registry: JobRegistry | None = None


def get_registry() -> JobRegistry:
    """Lazy module-level singleton."""
    global _registry
    if _registry is None:
        _registry = JobRegistry()
    return _registry


def reset_registry() -> None:
    """Test helper: clear the singleton."""
    global _registry
    _registry = None


async def start_cleanup_loop(
    registry: JobRegistry,
    interval_sec: int = 3600,
    max_age_sec: int = 86400,
) -> None:
    """Background task: periodically purge old finished jobs.

    Cancellation-safe: catches CancelledError to allow clean shutdown.
    """
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await registry.cleanup_finished(max_age_sec=max_age_sec)
            except Exception:
                logger.exception("JobRegistry cleanup loop iteration failed")
    except asyncio.CancelledError:
        logger.debug("JobRegistry cleanup loop cancelled")
        raise
