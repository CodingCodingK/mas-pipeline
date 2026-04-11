"""In-memory job tracking infrastructure (D1).

Used to track long-running async tasks and stream their progress to clients
via SSE. First consumer: document ingestion (parse → chunk → embed → store).

The registry holds Jobs in process memory only. On restart, all in-flight
jobs are lost — clients should re-trigger. PG/Document.parsed remains the
source of truth for whether ingestion succeeded.
"""

from __future__ import annotations

from src.jobs.job import Job, JobStatus
from src.jobs.registry import JobRegistry, get_registry, start_cleanup_loop

__all__ = ["Job", "JobStatus", "JobRegistry", "get_registry", "start_cleanup_loop"]
