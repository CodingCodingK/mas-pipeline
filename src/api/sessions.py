"""REST endpoints for chat sessions, messages, and SSE event subscription.

Phase 6.1: thin layer that delegates to ChatSession CRUD + SessionRunner.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.auth import require_api_key
from src.db import get_db
from src.engine.session_registry import get_or_create_runner
from src.models import ChatSession, Conversation
from src.session.manager import append_message, get_messages

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])

# SSE keepalive cadence
_SSE_KEEPALIVE_SECONDS = 15.0


# ── Models ──────────────────────────────────────────────────


class CreateSessionBody(BaseModel):
    mode: Literal["chat", "autonomous"] = "chat"
    channel: str = "web"
    chat_id: str = Field(..., min_length=1)


class CreateSessionResponse(BaseModel):
    id: int
    mode: str
    session_key: str
    conversation_id: int


class SendMessageBody(BaseModel):
    content: Any  # str or list[dict]


class SendMessageResponse(BaseModel):
    message_index: int


class SessionDetail(BaseModel):
    id: int
    mode: str
    status: str
    project_id: int
    conversation_id: int
    session_key: str
    created_at: str | None = None
    last_active_at: str | None = None


class MessagesPage(BaseModel):
    items: list[dict]
    total: int


# ── Helpers ─────────────────────────────────────────────────


async def backfill_events_from(conv_id: int, last_event_id: int):
    """Yield SSE lines for messages with index > last_event_id.

    Pulled out of `session_events` so it can be unit-tested without
    actually streaming an HTTP response (TestClient + StreamingResponse +
    ASGITransport all fail at infinite SSE generators on Windows).

    Each yielded chunk is a complete SSE event terminated by a blank line.
    """
    history = await get_messages(conv_id)
    for idx, msg in enumerate(history[last_event_id + 1:], start=last_event_id + 1):
        payload = json.dumps({"index": idx, "message": msg}, ensure_ascii=False)
        yield f"id: {idx}\nevent: message\ndata: {payload}\n\n"


async def _load_session(session_id: int) -> ChatSession:
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalars().first()
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session


# ── Endpoints ───────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
)
async def create_session(project_id: int, body: CreateSessionBody) -> CreateSessionResponse:
    """Create or return existing chat session for (channel, chat_id) pair.

    Idempotent: a second call with the same channel+chat_id returns the
    existing session unchanged (mode is fixed at first creation).
    """
    session_key = f"{body.channel}:{body.chat_id}"

    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.session_key == session_key)
        )
        existing = result.scalars().first()
        if existing is not None:
            return CreateSessionResponse(
                id=existing.id,
                mode=existing.mode,
                session_key=existing.session_key,
                conversation_id=existing.conversation_id,
            )

        conv = Conversation(project_id=project_id)
        db.add(conv)
        await db.flush()
        session = ChatSession(
            session_key=session_key,
            channel=body.channel,
            chat_id=body.chat_id,
            project_id=project_id,
            conversation_id=conv.id,
            mode=body.mode,
        )
        db.add(session)
        await db.flush()
        await db.refresh(session)

    return CreateSessionResponse(
        id=session.id,
        mode=session.mode,
        session_key=session.session_key,
        conversation_id=session.conversation_id,
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
    status_code=202,
)
async def send_message(session_id: int, body: SendMessageBody) -> SendMessageResponse:
    """Append a user message and ensure a SessionRunner is active."""
    session = await _load_session(session_id)

    message: dict = {"role": "user", "content": body.content}
    await append_message(session.conversation_id, message)

    msgs = await get_messages(session.conversation_id)
    message_index = len(msgs) - 1

    runner, created = await get_or_create_runner(
        session_id=session.id,
        mode=session.mode,
        project_id=session.project_id,
        conversation_id=session.conversation_id,
    )
    if not created:
        runner.notify_new_message()

    return SendMessageResponse(message_index=message_index)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: int, request: Request) -> StreamingResponse:
    """SSE stream of session events.

    Honors `Last-Event-ID` request header for backfill from
    `Conversation.messages[last_id+1:]` (one event per message), then live
    streams events emitted by the SessionRunner.
    """
    session = await _load_session(session_id)

    last_event_id = -1
    raw = request.headers.get("Last-Event-ID")
    if raw is not None:
        try:
            last_event_id = int(raw)
        except ValueError:
            last_event_id = -1

    runner, _created = await get_or_create_runner(
        session_id=session.id,
        mode=session.mode,
        project_id=session.project_id,
        conversation_id=session.conversation_id,
    )

    queue = runner.add_subscriber()
    conv_id = session.conversation_id

    async def event_stream():
        from src.api.metrics import sse_connect, sse_disconnect
        sse_connect()
        try:
            # ── Backfill ──
            if last_event_id >= 0:
                try:
                    async for line in backfill_events_from(conv_id, last_event_id):
                        yield line
                except Exception:
                    logger.exception("SSE backfill failed for session %d", session_id)

            # ── Live stream ──
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                try:
                    sse_payload = event.to_sse()
                except Exception:
                    logger.exception("SSE serialization failed")
                    continue

                yield sse_payload
        finally:
            runner.remove_subscriber(queue)
            sse_disconnect()

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


class SessionListItem(BaseModel):
    id: int
    mode: str
    status: str
    created_at: str | None = None
    last_active_at: str | None = None


class SessionList(BaseModel):
    items: list[SessionListItem]


@router.get("/projects/{project_id}/sessions", response_model=SessionList)
async def list_sessions(project_id: int) -> SessionList:
    """List chat sessions for a project, newest first."""
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.project_id == project_id)
            .order_by(ChatSession.last_active_at.desc())
        )
        sessions = result.scalars().all()
    return SessionList(
        items=[
            SessionListItem(
                id=s.id,
                mode=s.mode,
                status=s.status,
                created_at=s.created_at.isoformat() if s.created_at else None,
                last_active_at=s.last_active_at.isoformat() if s.last_active_at else None,
            )
            for s in sessions
        ]
    )


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: int) -> SessionDetail:
    session = await _load_session(session_id)
    return SessionDetail(
        id=session.id,
        mode=session.mode,
        status=session.status,
        project_id=session.project_id,
        conversation_id=session.conversation_id,
        session_key=session.session_key,
        created_at=session.created_at.isoformat() if session.created_at else None,
        last_active_at=(
            session.last_active_at.isoformat() if session.last_active_at else None
        ),
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int) -> None:
    """Delete a chat session and its conversation."""
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalars().first()
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        conv_id = session.conversation_id
        await db.delete(session)
        # Also delete the conversation record
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = conv_result.scalars().first()
        if conv is not None:
            await db.delete(conv)


@router.get("/sessions/{session_id}/messages", response_model=MessagesPage)
async def list_session_messages(
    session_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> MessagesPage:
    session = await _load_session(session_id)
    all_msgs = await get_messages(session.conversation_id)
    page = all_msgs[offset : offset + limit]
    return MessagesPage(items=page, total=len(all_msgs))
