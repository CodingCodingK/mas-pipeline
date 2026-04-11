"""Integration tests: bus Gateway → SessionRunner registry against real PG/Redis.

Requires docker compose services running. Mocks `create_agent` / `agent_loop`
so no actual LLM call happens — we're verifying that the bus dispatch path
shares a SessionRunner with the REST path for the same chat_session_id, and
that concurrent bus messages serialize through one runner.

The mocked `agent_loop` emits `text_delta` + `done` events AND appends an
assistant message to `state.messages` so the runner's `_persist_new_messages`
writes it to PG (keeping REST-visible history consistent).

Run: python scripts/test_bus_session_runner_integration.py

Fully mocked equivalents of the /resume bypass, subscriber timeout, and
non-text event filtering paths live in `scripts/test_claw_gateway.py`; this
file tests only the wiring concerns that require real PG + the global runner
registry.
"""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text

from src.bus.bus import MessageBus
from src.bus.gateway import Gateway
from src.bus.message import InboundMessage
from src.db import get_db
from src.engine.session_registry import _session_runners, get_or_create_runner, shutdown_all
from src.models import ChatSession, Conversation, Project
from src.session.manager import get_messages
from src.streaming.events import StreamEvent

passed = 0
failed = 0
skipped = 0


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


def skip_all(reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  [SKIP] all bus integration tests — {reason}")


# ── Fake agent_loop ────────────────────────────────────────


def make_fake_agent_loop(reply_text: str = "ok"):
    """Async generator that mimics a turn: one text_delta + done, plus writes
    the assistant message into `state.messages` so the runner persists it."""

    async def fake_loop(state):
        state.messages.append({"role": "assistant", "content": reply_text})
        yield StreamEvent(type="text_delta", content=reply_text)
        yield StreamEvent(type="done", finish_reason="stop")

    return fake_loop


def _make_fake_state():
    state = MagicMock()
    state.messages = [{"role": "system", "content": "fake"}]
    state.tool_context = MagicMock()
    state.tool_context.session_id = None
    state.tool_context.conversation_id = None
    state.running_agent_count = 0
    return state


# ── DB helpers ─────────────────────────────────────────────


async def _cleanup() -> None:
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession.conversation_id).where(ChatSession.channel == "bus_test")
        )
        conv_ids = list(result.scalars().all())
        await db.execute(delete(ChatSession).where(ChatSession.channel == "bus_test"))
        if conv_ids:
            await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))


async def _ensure_project(project_id: int = 1) -> None:
    async with get_db() as db:
        existing = await db.get(Project, project_id)
        if existing is not None:
            return
        await db.execute(
            text(
                "INSERT INTO projects (id, user_id, name, pipeline, status) "
                "VALUES (:id, 1, 'bus-integration', 'blog_generation', 'active')"
            ),
            {"id": project_id},
        )


# ── Tests ──────────────────────────────────────────────────


async def test_first_bus_message_creates_runner():
    print("\n=== case B: first bus message creates runner ===")
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    msg = InboundMessage(channel="bus_test", sender_id="u1", chat_id="caseB", content="hello")
    await gw._process_message(msg)

    # Runner should still be alive right after (idle timeout is long)
    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.channel == "bus_test", ChatSession.chat_id == "caseB"
            )
        )
        session = result.scalars().first()

    check("session created in PG", session is not None)
    if session is None:
        return
    check("runner registered", session.id in _session_runners)

    check("outbound published", not bus.outbound.empty())
    out = await bus.consume_outbound()
    check("outbound content matches fake reply", out.content == "ok")

    # User message should be in PG
    messages = await get_messages(session.conversation_id)
    user_msgs = [m for m in messages if m.get("role") == "user"]
    check("user message persisted", any(m.get("content") == "hello" for m in user_msgs))


async def test_bus_and_rest_share_runner():
    print("\n=== case A: bus and REST share one runner ===")
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    # First: a bus message — this creates the runner
    msg1 = InboundMessage(
        channel="bus_test", sender_id="u1", chat_id="caseA", content="msg1-bus"
    )
    await gw._process_message(msg1)

    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.channel == "bus_test", ChatSession.chat_id == "caseA"
            )
        )
        session = result.scalars().first()

    check("session created", session is not None)
    if session is None:
        return
    runner_after_bus = _session_runners.get(session.id)
    check("runner exists after bus message", runner_after_bus is not None)

    # Now simulate REST path: obtain runner via the same registry call
    runner_after_rest = await get_or_create_runner(
        session_id=session.id,
        mode=session.mode,
        project_id=session.project_id,
        conversation_id=session.conversation_id,
    )
    check("REST obtains same runner instance", runner_after_rest is runner_after_bus)
    check("registry has exactly one runner for this session", len(
        [k for k in _session_runners if k == session.id]
    ) == 1)

    # Second bus message against the same session
    msg2 = InboundMessage(
        channel="bus_test", sender_id="u1", chat_id="caseA", content="msg2-bus"
    )
    await gw._process_message(msg2)

    # Both user messages should end up in the same conversation
    messages = await get_messages(session.conversation_id)
    user_contents = [m.get("content") for m in messages if m.get("role") == "user"]
    check("first user message preserved", "msg1-bus" in user_contents)
    check("second user message appended", "msg2-bus" in user_contents)
    check(
        "user messages appear in order",
        user_contents.index("msg1-bus") < user_contents.index("msg2-bus"),
    )

    # Still one runner
    check(
        "registry still has one runner for session after 2nd bus msg",
        session.id in _session_runners and len(
            [k for k in _session_runners if k == session.id]
        ) == 1,
    )


async def test_concurrent_bus_messages_serialize():
    print("\n=== case C: concurrent bus messages serialize via runner ===")
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    # Fire two messages on the same session concurrently
    msg_a = InboundMessage(
        channel="bus_test", sender_id="u1", chat_id="caseC", content="concurrent-A"
    )
    msg_b = InboundMessage(
        channel="bus_test", sender_id="u1", chat_id="caseC", content="concurrent-B"
    )

    await asyncio.gather(
        gw._process_message(msg_a),
        gw._process_message(msg_b),
    )

    async with get_db() as db:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.channel == "bus_test", ChatSession.chat_id == "caseC"
            )
        )
        session = result.scalars().first()

    check("session created", session is not None)
    if session is None:
        return

    # Both outbounds should be published
    outbounds: list[str] = []
    while not bus.outbound.empty():
        out = await bus.consume_outbound()
        outbounds.append(out.content)

    check("two outbounds published", len(outbounds) == 2, detail=str(outbounds))

    # Both user messages should be in the conversation
    messages = await get_messages(session.conversation_id)
    user_contents = [m.get("content") for m in messages if m.get("role") == "user"]
    check("both concurrent user messages persisted", set(["concurrent-A", "concurrent-B"]) <= set(user_contents))

    # Exactly one runner for the session
    check("registry has one runner", session.id in _session_runners)


async def main_async():
    try:
        await _cleanup()
        await _ensure_project(1)
    except Exception as exc:  # noqa: BLE001 — treat as env unavailable
        skip_all(f"DB/Redis not reachable: {type(exc).__name__}: {exc}")
        return

    try:
        with patch(
            "src.agent.factory.create_agent",
            new=AsyncMock(side_effect=lambda *a, **k: _make_fake_state()),
        ), patch("src.engine.session_runner.agent_loop", new=make_fake_agent_loop("ok")):
            await test_first_bus_message_creates_runner()
            await test_bus_and_rest_share_runner()
            await test_concurrent_bus_messages_serialize()
    finally:
        # Drain runners before cleanup so _persist_new_messages doesn't race
        # the DELETE statement.
        try:
            await shutdown_all()
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] shutdown_all failed: {exc}")
        try:
            await _cleanup()
        except Exception as exc:  # noqa: BLE001
            print(f"  [WARN] cleanup failed: {exc}")


def main():
    asyncio.run(main_async())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        sys.exit(1)
    if skipped and not passed:
        print("All tests skipped (environment unavailable).")
        return
    print("All checks passed!")


if __name__ == "__main__":
    main()
