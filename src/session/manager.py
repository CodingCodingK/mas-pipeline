"""Session manager: Conversation (PG)."""

from __future__ import annotations

import logging
from datetime import datetime

from src.db import get_db
from src.models import Conversation

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
