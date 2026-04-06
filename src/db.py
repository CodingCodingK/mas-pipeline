"""Database connection layer: async PostgreSQL (psycopg) + Redis."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.project.config import get_settings

# ── PostgreSQL ──────────────────────────────────────────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database.postgres_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an async DB session, auto-commits on success."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Redis ───────────────────────────────────────────────────

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.database.redis_url,
            decode_responses=True,
        )
    return _redis


# ── Lifecycle ───────────────────────────────────────────────

async def init_db() -> None:
    """Verify database connections on startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text("SELECT 1")
        )

    r = get_redis()
    await r.ping()


async def close_db() -> None:
    """Clean up connections on shutdown."""
    global _engine, _redis, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _redis:
        await _redis.aclose()
        _redis = None
