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

from src.api.agents import router as agents_router
from src.api.metrics import metrics_endpoint, setup_metrics
from src.api.export import router as export_router
from src.api.files import router as files_router
from src.api.jobs import router as jobs_router
from src.api.pipelines import router as pipelines_router
from src.api.knowledge import router as knowledge_router
from src.api.projects import router as projects_router
from src.api.runs import router as runs_router
from src.api.sessions import router as sessions_router
from src.events.bus import EventBus
from src.jobs import get_registry as get_jobs_registry
from src.jobs.registry import start_cleanup_loop as start_jobs_cleanup_loop
from src.notify import NullNotifier, Notifier, set_notifier
from src.notify.api import router as notify_router
from src.notify.channels import DiscordChannel, SseChannel, WechatChannel
from src.telemetry.api import admin_router as telemetry_admin_router
from src.telemetry.api import router as telemetry_router
from src.db import check_pool_sizing, close_db, init_db
from src.engine.session_registry import (
    _idle_gc_task,
    _listen_session_wakeup,
    shutdown_all,
)
from src.project.config import get_settings
from src.sandbox import init_sandbox
from src.telemetry import (
    NullTelemetryCollector,
    TelemetryCollector,
    set_collector,
)

logger = logging.getLogger(__name__)


def _check_worker_concurrency() -> None:
    """Hard-fail if any worker-count env var > 1.

    SessionRunner keeps in-process state (runner registry, SSE subscriber
    queues, bus subscribers). Multi-worker deployments would route the same
    session to different processes each holding its own state — silent data
    loss. Single-worker is the contract until sticky routing lands.

    Uvicorn --reload does NOT set these vars, so dev hot-reload still works.
    """
    for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = os.environ.get(var)
        if raw and raw.strip() not in ("", "1"):
            logger.critical(
                "%s=%s rejected. mas-pipeline runs single-worker only "
                "(SessionRunner holds in-process state). See "
                ".plan/rest_api_deployment_risks.md risk #1. Exiting.",
                var,
                raw,
            )
            raise SystemExit(1)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    print(f"[mas-pipeline] Starting with model tiers: {settings.models}")

    from src.llm.router import validate_model_providers
    provider_errors = validate_model_providers()
    if provider_errors:
        for err in provider_errors:
            print(f"[mas-pipeline] ⚠ {err}")
        raise RuntimeError(
            "Model-provider configuration invalid. "
            "Check settings.yaml: each tier's model must have a provider with a valid API key."
        )
    print("[mas-pipeline] Model-provider bindings verified")

    sandbox_mode = init_sandbox(settings.sandbox)
    print(f"[mas-pipeline] Sandbox mode: {sandbox_mode.value}")
    _check_worker_concurrency()

    await init_db()
    print("[mas-pipeline] Database connections verified")
    await check_pool_sizing()

    # Bind Prometheus gauge callbacks to live registries + engine pool.
    setup_metrics()

    # Event bus must exist before any consumer subscribes.
    tele_cfg = settings.telemetry
    bus = EventBus(queue_size=tele_cfg.max_queue_size)
    app.state.event_bus = bus

    # Telemetry collector subscribes to the bus as "telemetry".
    if tele_cfg.enabled:
        from src.db import get_session_factory
        collector = TelemetryCollector(
            db_session_factory=get_session_factory(),
            bus=bus,
            enabled=True,
            preview_length=tele_cfg.preview_length,
            batch_size=tele_cfg.batch_size,
            flush_interval_sec=tele_cfg.flush_interval_sec,
            max_queue_size=tele_cfg.max_queue_size,
            pricing_table_path=tele_cfg.pricing_table_path,
        )
        await collector.start()
    else:
        collector = NullTelemetryCollector(bus=bus)
    set_collector(collector)
    app.state.telemetry_collector = collector

    # Notify layer subscribes to the bus as "notify" after telemetry.
    notify_cfg = settings.notify
    notifier: Notifier
    if notify_cfg.enabled:
        from src.db import get_session_factory as _get_session_factory
        session_factory = _get_session_factory()
        channels = [SseChannel(default_max_size=notify_cfg.sse_queue_size)]
        if notify_cfg.wechat_webhook_url:
            channels.append(WechatChannel(notify_cfg.wechat_webhook_url))
        if notify_cfg.discord_webhook_url:
            channels.append(DiscordChannel(notify_cfg.discord_webhook_url))
        notifier = Notifier(
            bus=bus,
            channels=channels,
            rules=None,
            session_factory=session_factory,
            queue_size=notify_cfg.notify_queue_size,
        )
        await notifier.start()
    else:
        notifier = NullNotifier(bus=bus)
    set_notifier(notifier)
    app.state.notifier = notifier

    # Phase 6.1 background tasks: idle GC + cross-process LISTEN.
    gc_task = asyncio.create_task(_idle_gc_task(), name="session-registry-gc")
    listen_task = asyncio.create_task(
        _listen_session_wakeup(), name="session-registry-listen"
    )

    # Phase 6.4: in-memory job registry + periodic cleanup of finished jobs.
    jobs_registry = get_jobs_registry()
    jobs_cleanup_task = asyncio.create_task(
        start_jobs_cleanup_loop(jobs_registry),
        name="jobs-registry-cleanup",
    )

    try:
        yield
    finally:
        try:
            await notifier.stop(timeout_seconds=5.0)
        except Exception:
            logger.exception("notifier stop failed")

        try:
            await collector.stop()
        except Exception:
            logger.exception("telemetry collector stop failed")

        # Close the bus after all consumers have stopped draining.
        try:
            bus.close()
        except Exception:
            logger.exception("event bus close failed")

        # Graceful SessionRunner shutdown.
        try:
            await shutdown_all(timeout_seconds=5.0)
        except Exception:
            logger.exception("shutdown_all failed")

        for task in (gc_task, listen_task, jobs_cleanup_task):
            task.cancel()
        for task in (gc_task, listen_task, jobs_cleanup_task):
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
api_router.include_router(telemetry_router)
api_router.include_router(telemetry_admin_router)
api_router.include_router(notify_router)
api_router.include_router(files_router)
api_router.include_router(knowledge_router)
api_router.include_router(jobs_router)
api_router.include_router(export_router)
api_router.include_router(agents_router)
api_router.include_router(pipelines_router)
app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Prometheus scrape endpoint — root prefix, unauthenticated.
app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)


if __name__ == "__main__":
    import selectors

    import uvicorn

    settings = get_settings()

    if platform.system() == "Windows" and not settings.server.reload:
        # uvicorn.run() calls asyncio.run() which creates a fresh event loop,
        # ignoring the module-level WindowsSelectorEventLoopPolicy.
        # Drive the server ourselves so we can pass loop_factory.
        config = uvicorn.Config(
            "src.main:app",
            host=settings.server.host,
            port=settings.server.port,
        )
        server = uvicorn.Server(config)
        asyncio.run(
            server.serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    else:
        uvicorn.run(
            "src.main:app",
            host=settings.server.host,
            port=settings.server.port,
            reload=settings.server.reload,
        )
