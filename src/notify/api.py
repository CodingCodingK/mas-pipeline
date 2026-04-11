"""REST + SSE API for notify layer."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.auth import require_api_key
from src.auth.user import get_current_user
from src.db import get_session_factory
from src.notify import preferences
from src.notify.channels.sse import SseChannel
from src.notify.notifier import get_notifier
from src.project.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notify", tags=["notify"], dependencies=[Depends(require_api_key)]
)


class PreferenceUpdate(BaseModel):
    event_type: str
    channels: list[str]


_VALID_EVENT_TYPES = {
    "run_started",
    "run_completed",
    "run_failed",
    "human_review_needed",
    "agent_progress",
}


def _get_sse_channel() -> SseChannel:
    notifier = get_notifier()
    for ch in getattr(notifier, "channels", []):
        if isinstance(ch, SseChannel):
            return ch
    raise HTTPException(status_code=503, detail="sse channel not configured")


def _configured_channel_names() -> list[str]:
    notifier = get_notifier()
    return [ch.name for ch in getattr(notifier, "channels", [])]


@router.get("/stream")
async def notify_stream(request: Request) -> StreamingResponse:
    """SSE stream of notifications for the authenticated user."""
    user = await get_current_user()
    sse = _get_sse_channel()
    settings = get_settings()
    heartbeat = max(1, int(settings.notify.sse_heartbeat_sec))
    queue = sse.register(user.id, max_size=settings.notify.sse_queue_size)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    notification = await asyncio.wait_for(
                        queue.get(), timeout=heartbeat
                    )
                except asyncio.TimeoutError:
                    yield ":heartbeat\n\n"
                    continue
                try:
                    data = json.dumps(notification.to_dict(), ensure_ascii=False)
                except Exception:
                    logger.exception("notify stream: serialization failed")
                    continue
                yield (
                    f"event: {notification.event_type}\n"
                    f"data: {data}\n"
                    f"id: {notification.notification_id}\n\n"
                )
        finally:
            sse.unregister(user.id, queue)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )


@router.get("/preferences")
async def get_preferences() -> dict[str, list[str]]:
    user = await get_current_user()
    return await preferences.get_all(user.id, get_session_factory())


@router.put("/preferences")
async def put_preferences(body: PreferenceUpdate) -> dict[str, list[str]]:
    if body.event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid event_type '{body.event_type}'",
        )
    valid_channels = set(_configured_channel_names())
    for channel in body.channels:
        if channel not in valid_channels:
            raise HTTPException(
                status_code=400,
                detail=f"invalid channel '{channel}'",
            )
    user = await get_current_user()
    factory = get_session_factory()
    await preferences.set(user.id, body.event_type, body.channels, factory)
    return await preferences.get_all(user.id, factory)


@router.get("/channels")
async def list_channels() -> list[str]:
    return _configured_channel_names()
