"""FastAPI application entry point."""

from __future__ import annotations

import platform

# Windows: psycopg async requires SelectorEventLoop
if platform.system() == "Windows":
    import asyncio
    import selectors

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from src.db import close_db, init_db
from src.project.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    settings = get_settings()
    print(f"[mas-pipeline] Starting with model tiers: {settings.models}")
    await init_db()
    print("[mas-pipeline] Database connections verified")
    yield
    await close_db()
    print("[mas-pipeline] Shutdown complete")


app = FastAPI(
    title="mas-pipeline",
    description="Multi-Agent System content production pipeline engine",
    version="0.1.0",
    lifespan=lifespan,
)


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
