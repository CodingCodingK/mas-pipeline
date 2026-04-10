"""Phase 6.1 §10.5 — SSE Last-Event-ID backfill end-to-end.

WHY THIS DOESN'T USE httpx + ASGITransport:
    httpx.ASGITransport collects every body chunk into an in-memory list and
    only returns the response once `more_body=False` arrives. SSE handlers
    are infinite generators by design, so the transport never returns and
    every assertion deadlocks. TestClient (sync) has the same problem on
    Windows because the bridging anyio loop blocks waiting for chunks that
    arrive only after each `await`.

WHAT WE TEST INSTEAD:
    The backfill yield logic was extracted into `backfill_events_from(conv_id,
    last_event_id)` — a pure async generator. We exercise it directly against
    a real PG-backed Conversation, parse the SSE frames it produces, and
    assert the indices + payloads. This is the *exact* code path that runs
    inside the SSE endpoint, minus the StreamingResponse wrapper.

    We also smoke-check that the SSE endpoint is mounted on the app and
    delegates to the helper (route is registered, dependencies wired).

Run: python scripts/test_rest_api_sse_backfill.py
"""
from __future__ import annotations

import asyncio
import json
import platform
import sys
from pathlib import Path

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text

from src.api.sessions import backfill_events_from
from src.db import get_db
from src.models import ChatSession, Conversation, Project

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


# ── DB helpers ───────────────────────────────────────────────


async def _ensure_project(project_id: int = 1) -> None:
    async with get_db() as db:
        existing = await db.get(Project, project_id)
        if existing is not None:
            return
        await db.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, status) "
                "VALUES (:id, 1, 'sse-test', 'blog_generation', 'active')"
            ),
            {"id": project_id},
        )


async def _cleanup() -> None:
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession.conversation_id).where(
                ChatSession.channel == "ssetest"
            )
        )
        conv_ids = list(result.scalars().all())
        await db.execute(
            delete(ChatSession).where(ChatSession.channel == "ssetest")
        )
        if conv_ids:
            await db.execute(
                delete(Conversation).where(Conversation.id.in_(conv_ids))
            )


async def _make_seeded_conversation(messages: list[dict]) -> int:
    """Create a conversation, attach a chat_session, set messages, return conv_id."""
    async with get_db() as db:
        conv = Conversation(project_id=1, messages=list(messages))
        db.add(conv)
        await db.flush()
        sess = ChatSession(
            session_key=f"ssetest:auto-{conv.id}",
            channel="ssetest",
            chat_id=f"auto-{conv.id}",
            project_id=1,
            conversation_id=conv.id,
            mode="chat",
        )
        db.add(sess)
        await db.flush()
        return conv.id


# ── SSE frame parser ─────────────────────────────────────────


def _parse_sse(text: str) -> list[dict]:
    """Parse a stream of SSE frames into a list of {id, event, data} dicts."""
    frames: list[dict] = []
    cur: dict = {}
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line:
            if cur:
                frames.append(cur)
                cur = {}
            continue
        if line.startswith("id:"):
            cur["id"] = line.split(":", 1)[1].strip()
        elif line.startswith("event:"):
            cur["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            cur["data"] = line.split(":", 1)[1].strip()
    if cur:
        frames.append(cur)
    return frames


# ── Tests ────────────────────────────────────────────────────


async def test_backfill_helper_basic() -> None:
    print("\n=== backfill_events_from: Last-Event-ID=1 yields [2,3] ===")

    conv_id = await _make_seeded_conversation([
        {"role": "user", "content": "u0"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a3"},
    ])

    chunks: list[str] = []
    async for chunk in backfill_events_from(conv_id, 1):
        chunks.append(chunk)

    text = "".join(chunks)
    frames = _parse_sse(text)

    check("yielded 2 frames", len(frames) == 2, str(len(frames)))
    check("frame ids = [2, 3]",
          [f.get("id") for f in frames] == ["2", "3"])
    check("event types all 'message'",
          all(f.get("event") == "message" for f in frames))

    # Decode data payloads
    parsed = [json.loads(f["data"]) for f in frames]
    check("frame[0].index == 2", parsed[0]["index"] == 2)
    check("frame[0].message content == u2",
          parsed[0]["message"]["content"] == "u2")
    check("frame[1].index == 3", parsed[1]["index"] == 3)
    check("frame[1].message role == assistant",
          parsed[1]["message"]["role"] == "assistant")


async def test_backfill_at_zero() -> None:
    print("\n=== backfill_events_from: Last-Event-ID=0 yields [1,2,3] ===")

    conv_id = await _make_seeded_conversation([
        {"role": "user", "content": "m0"},
        {"role": "user", "content": "m1"},
        {"role": "user", "content": "m2"},
        {"role": "user", "content": "m3"},
    ])
    chunks = []
    async for chunk in backfill_events_from(conv_id, 0):
        chunks.append(chunk)
    frames = _parse_sse("".join(chunks))
    check("3 frames after id=0", len(frames) == 3)
    check("ids = [1,2,3]", [f["id"] for f in frames] == ["1", "2", "3"])


async def test_backfill_caught_up() -> None:
    print("\n=== backfill_events_from: caught up returns nothing ===")

    conv_id = await _make_seeded_conversation([
        {"role": "user", "content": "only"},
    ])
    chunks = []
    async for chunk in backfill_events_from(conv_id, 0):
        chunks.append(chunk)
    check("zero frames when client at last index", len(chunks) == 0)


async def test_backfill_past_end() -> None:
    print("\n=== backfill_events_from: Last-Event-ID > history yields nothing ===")

    conv_id = await _make_seeded_conversation([
        {"role": "user", "content": "x"},
        {"role": "user", "content": "y"},
    ])
    chunks = []
    async for chunk in backfill_events_from(conv_id, 99):
        chunks.append(chunk)
    check("zero frames past end", len(chunks) == 0)


async def test_backfill_empty_conversation() -> None:
    print("\n=== backfill_events_from: empty conversation yields nothing ===")

    conv_id = await _make_seeded_conversation([])
    chunks = []
    async for chunk in backfill_events_from(conv_id, -1):
        chunks.append(chunk)
    check("zero frames empty conv", len(chunks) == 0)


async def test_backfill_unicode_payload() -> None:
    print("\n=== backfill_events_from: unicode payload survives JSON encoding ===")

    conv_id = await _make_seeded_conversation([
        {"role": "user", "content": "你好 🌏"},
        {"role": "assistant", "content": "回复"},
    ])
    chunks = []
    async for chunk in backfill_events_from(conv_id, -1):
        chunks.append(chunk)
    text = "".join(chunks)
    frames = _parse_sse(text)
    check("2 unicode frames", len(frames) == 2)
    parsed_data = [json.loads(f["data"]) for f in frames]
    check("unicode preserved",
          parsed_data[0]["message"]["content"] == "你好 🌏")


def test_route_registered() -> None:
    print("\n=== /api/sessions/{session_id}/events route is mounted ===")
    import src.main as main_module
    paths = {getattr(r, "path", "") for r in main_module.app.routes}
    check(
        "sse events endpoint registered",
        "/api/sessions/{session_id}/events" in paths,
    )


def test_endpoint_uses_helper() -> None:
    print("\n=== session_events delegates to backfill_events_from ===")
    import inspect
    from src.api import sessions
    src = inspect.getsource(sessions.session_events)
    check(
        "session_events references backfill_events_from",
        "backfill_events_from" in src,
    )


# ── Main ─────────────────────────────────────────────────────


async def _async_main() -> None:
    await _cleanup()
    await _ensure_project(1)
    try:
        await test_backfill_helper_basic()
        await test_backfill_at_zero()
        await test_backfill_caught_up()
        await test_backfill_past_end()
        await test_backfill_empty_conversation()
        await test_backfill_unicode_payload()
    finally:
        try:
            await _cleanup()
        except Exception as exc:
            print(f"  [WARN] cleanup failed: {exc}")


def main() -> None:
    asyncio.run(_async_main())
    test_route_registered()
    test_endpoint_uses_helper()
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")


if __name__ == "__main__":
    main()
