"""ChatSession CRUD with Redis cache layer for external platform sessions."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select

from src.db import get_db, get_redis
from src.models import ChatSession, Conversation
from src.session.manager import clean_orphan_messages, get_messages

logger = logging.getLogger(__name__)

# Redis key prefix and default TTL
_CACHE_PREFIX = "chat_session:"
_DEFAULT_TTL_HOURS = 24


async def resolve_session(
    session_key: str,
    channel: str,
    chat_id: str,
    project_id: int,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> ChatSession:
    """Look up or create a ChatSession.

    1. Check Redis cache for session_key
    2. Fall back to PG query
    3. Create new ChatSession + Conversation if not found
    4. Cache result in Redis
    """
    redis = get_redis()
    cache_key = f"{_CACHE_PREFIX}{session_key}"

    # 1. Redis cache hit
    cached = await redis.get(cache_key)
    if cached is not None:
        data = json.loads(cached)
        # Reconstruct a lightweight ChatSession from cached data
        session = ChatSession(
            id=data["id"],
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            project_id=data["project_id"],
            conversation_id=data["conversation_id"],
            status="active",
        )
        return session

    # 2. PG lookup
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.session_key == session_key)
        )
        session = result.scalars().first()

        if session is not None:
            # Cache and return
            await _cache_session(redis, cache_key, session, ttl_hours)
            return session

        # 3. Create new Conversation + ChatSession
        # Use try/except for race condition: concurrent requests may both
        # miss cache and PG, then race to insert the same session_key.
        try:
            conv = Conversation(project_id=project_id)
            db.add(conv)
            await db.flush()  # Get conv.id

            session = ChatSession(
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
                project_id=project_id,
                conversation_id=conv.id,
            )
            db.add(session)
            await db.flush()
            await db.refresh(session)

            logger.info(
                "Created ChatSession '%s' → conversation %d",
                session_key, conv.id,
            )
        except Exception:
            # Race condition: another request created it first. Re-query.
            await db.rollback()
            result = await db.execute(
                select(ChatSession).where(ChatSession.session_key == session_key)
            )
            session = result.scalars().first()
            if session is None:
                raise  # Genuine error, not a race condition

    # Cache the new session
    await _cache_session(redis, cache_key, session, ttl_hours)
    return session


async def refresh_session(
    session_key: str,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> None:
    """Update last_active_at in PG and refresh Redis TTL."""
    redis = get_redis()
    cache_key = f"{_CACHE_PREFIX}{session_key}"

    # Refresh Redis TTL
    await redis.expire(cache_key, ttl_hours * 3600)

    # Update PG
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.session_key == session_key)
        )
        session = result.scalars().first()
        if session is not None:
            session.last_active_at = datetime.utcnow()


async def get_session_history(
    conversation_id: int,
    max_messages: int = 50,
) -> list[dict]:
    """Load messages from Conversation, clean orphans, trim to max_messages."""
    messages = await get_messages(conversation_id)
    messages = clean_orphan_messages(messages)

    # Trim to last N messages
    if max_messages > 0 and len(messages) > max_messages:
        messages = messages[-max_messages:]

    # Ensure we don't start mid-turn (with a tool result)
    while messages and messages[0].get("role") == "tool":
        messages = messages[1:]

    return messages


async def _cache_session(
    redis: object,
    cache_key: str,
    session: ChatSession,
    ttl_hours: int,
) -> None:
    """Write session mapping to Redis with TTL."""
    data = json.dumps({
        "id": session.id,
        "project_id": session.project_id,
        "conversation_id": session.conversation_id,
    })
    await redis.set(cache_key, data, ex=ttl_hours * 3600)
