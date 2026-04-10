"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import platform

# Windows: psycopg async requires SelectorEventLoop
if platform.system() == "Windows":
    import selectors  # noqa: F401 — imported for side-effect on some setups

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI

from src.api.projects import router as projects_router
from src.api.runs import router as runs_router
from src.api.sessions import router as sessions_router
from src.db import close_db, init_db
from src.engine.session_registry import (
    _idle_gc_task,
    _listen_session_wakeup,
    shutdown_all,
)
from src.project.config import get_settings
from src.sandbox import init_sandbox

logger = logging.getLogger(__name__)


def _check_worker_concurrency() -> None:
    raw = os.environ.get("WEB_CONCURRENCY")
    if raw and raw != "1":
        logger.warning(
            "WEB_CONCURRENCY=%s detected. SessionRunner is single-process; "
            "multi-worker deployments need sticky routing (not yet implemented). "
            "Run with --workers 1 until then.",
            raw,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    print(f"[mas-pipeline] Starting with model tiers: {settings.models}")
    sandbox_mode = init_sandbox(settings.sandbox)
    print(f"[mas-pipeline] Sandbox mode: {sandbox_mode.value}")
    await init_db()
    print("[mas-pipeline] Database connections verified")

    _check_worker_concurrency()

    # Phase 6.1 background tasks: idle GC + cross-process LISTEN.
    gc_task = asyncio.create_task(_idle_gc_task(), name="session-registry-gc")
    listen_task = asyncio.create_task(
        _listen_session_wakeup(), name="session-registry-listen"
    )

    try:
        yield
    finally:
        # Graceful SessionRunner shutdown.
        try:
            await shutdown_all(timeout_seconds=5.0)
        except Exception:
            logger.exception("shutdown_all failed")

        for task in (gc_task, listen_task):
            task.cancel()
        for task in (gc_task, listen_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        await close_db()
        print("[mas-pipeline] Shutdown complete")


app = FastAPI(
    title="mas-pipeline",
    description="Multi-Agent System content production pipeline engine",
    version="0.1.0",
    lifespan=lifespan,
)

# /api router aggregates all Phase 6.1 endpoints.
api_router = APIRouter(prefix="/api")
api_router.include_router(projects_router)
api_router.include_router(sessions_router)
api_router.include_router(runs_router)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
    )
