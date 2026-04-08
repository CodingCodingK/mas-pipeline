"""Session manager: Conversation (PG) + Agent Session (Redis hot → PG cold)."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select

from src.db import get_db, get_redis
from src.models import AgentSessionRecord, Conversation
from src.project.config import get_settings

logger = logging.getLogger(__name__)


class ConversationNotFoundError(Exception):
    pass


# ── Conversation (PG) ──────────────────────────────────────


async def create_conversation(project_id: int) -> Conversation:
    """Create a new conversation for the given project."""
    async with get_db() as session:
        conv = Conversation(project_id=project_id)
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv


async def get_conversation(conversation_id: int) -> Conversation:
    """Retrieve a conversation by ID. Raises ConversationNotFoundError if missing."""
    async with get_db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise ConversationNotFoundError(
                f"Conversation not found: {conversation_id}"
            )
        return conv


async def append_message(conversation_id: int, message: dict) -> None:
    """Append a message to the conversation's messages list."""
    async with get_db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise ConversationNotFoundError(
                f"Conversation not found: {conversation_id}"
            )
        messages = list(conv.messages or [])
        messages.append(message)
        conv.messages = messages
        conv.updated_at = datetime.utcnow()
        await session.commit()


async def get_messages(conversation_id: int) -> list[dict]:
    """Get all messages for a conversation."""
    conv = await get_conversation(conversation_id)
    return list(conv.messages or [])


# ── Agent Session (Redis) ──────────────────────────────────


def _agent_session_key(agent_id: str) -> str:
    return f"agent_session:{agent_id}"


async def create_agent_session(agent_id: str, run_id: str) -> str:
    """Create an agent session in Redis with TTL. Returns the session key."""
    key = _agent_session_key(agent_id)
    redis = await get_redis()
    ttl_hours = get_settings().session.agent_ttl_hours
    await redis.expire(key, ttl_hours * 3600)
    return key


async def append_agent_message(session_key: str, message: dict) -> None:
    """Append a message to the agent session Redis list and refresh TTL."""
    redis = await get_redis()
    await redis.rpush(session_key, json.dumps(message, ensure_ascii=False))
    ttl_hours = get_settings().session.agent_ttl_hours
    await redis.expire(session_key, ttl_hours * 3600)


async def get_agent_messages(session_key: str) -> list[dict]:
    """Get all messages from an agent session in Redis."""
    redis = await get_redis()
    raw = await redis.lrange(session_key, 0, -1)
    return [json.loads(r) for r in raw]


# ── Agent Session Archival ─────────────────────────────────


async def archive_agent_session(session_key: str, agent_role: str) -> None:
    """Archive an agent session from Redis to PG, then delete the Redis key."""
    redis = await get_redis()

    # Read all messages from Redis
    raw = await redis.lrange(session_key, 0, -1)
    messages = [json.loads(r) for r in raw]

    # Extract agent_id from key
    agent_id = session_key.removeprefix("agent_session:")

    # Insert into PG
    async with get_db() as session:
        record = AgentSessionRecord(
            id=agent_id,
            agent_role=agent_role,
            messages=messages,
            archived_at=datetime.utcnow(),
        )
        session.add(record)
        await session.commit()

    # Delete Redis key
    await redis.delete(session_key)
    logger.info("Archived agent session %s (%d messages)", agent_id, len(messages))


# ── Orphan Cleanup ─────────────────────────────────────────


def clean_orphan_messages(messages: list[dict]) -> list[dict]:
    """Remove tool-result messages whose tool_call_id has no matching assistant tool_call."""
    valid_ids: set[str] = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id") or tc.get("tool_call_id")
                if tc_id:
                    valid_ids.add(tc_id)

    return [
        msg
        for msg in messages
        if msg.get("role") != "tool" or msg.get("tool_call_id") in valid_ids
    ]
