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

# ── LangGraph Checkpoint ────────────────────────────────────

_checkpointer = None
_checkpoint_conn = None


def _pg_conn_string() -> str:
    """Derive a plain psycopg connection string from the SQLAlchemy URL."""
    settings = get_settings()
    url = settings.database.postgres_url
    # SQLAlchemy: postgresql+psycopg://... → psycopg needs: postgresql://...
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


async def get_checkpointer():
    """Return the shared AsyncPostgresSaver singleton.

    Creates a dedicated psycopg async connection (separate from SQLAlchemy pool)
    and runs setup() to ensure checkpoint tables exist.
    """
    global _checkpointer, _checkpoint_conn
    if _checkpointer is None:
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _checkpoint_conn = await AsyncConnection.connect(
            _pg_conn_string(), autocommit=True, prepare_threshold=0, row_factory=dict_row
        )
        _checkpointer = AsyncPostgresSaver(conn=_checkpoint_conn)
        await _checkpointer.setup()
    return _checkpointer


# ── PostgreSQL ──────────────────────────────────────────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database.postgres_url,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_pre_ping=settings.database.pool_pre_ping,
            echo=False,
        )
    return _engine


async def check_pool_sizing() -> None:
    """Warn (do not fail) if the configured pool may exhaust PG max_connections.

    Runs `SHOW max_connections` and compares against pool_size + max_overflow.
    Informational only — ops may have reserved connections for other consumers.
    """
    import logging
    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    settings = get_settings()
    effective = settings.database.pool_size + settings.database.max_overflow

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SHOW max_connections"))
            row = result.scalar()
            pg_max = int(row) if row is not None else 0
    except Exception as exc:
        logger.warning("check_pool_sizing: SHOW max_connections failed: %s", exc)
        return

    if effective > pg_max - 10:
        logger.warning(
            "DB pool oversubscribed: pool_size(%d) + max_overflow(%d) = %d "
            "exceeds PG max_connections(%d) - 10 reserved. Reduce pool or raise "
            "PG max_connections.",
            settings.database.pool_size,
            settings.database.max_overflow,
            effective,
            pg_max,
        )


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
    global _engine, _redis, _session_factory, _checkpointer, _checkpoint_conn
    if _checkpoint_conn:
        await _checkpoint_conn.close()
        _checkpoint_conn = None
        _checkpointer = None
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _redis:
        await _redis.aclose()
        _redis = None
