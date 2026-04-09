"""Unit tests for src/bus/gateway.py — Gateway end-to-end, error handling, serial per-session."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.bus.gateway import Gateway
from src.bus.message import InboundMessage, OutboundMessage
from src.models import ChatSession

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


def make_inbound(content="hi", channel="discord", chat_id="c1"):
    return InboundMessage(channel=channel, sender_id="u1", chat_id=chat_id, content=content)


def make_session(session_key="discord:c1", conv_id=10):
    return ChatSession(
        id=1, session_key=session_key, channel="discord", chat_id="c1",
        project_id=1, conversation_id=conv_id,
    )


# === Gateway: end-to-end mock ===

print("=== Gateway: end-to-end ===")


async def test_e2e():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1, role="assistant")

    session = make_session()

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, return_value=session), \
         patch("src.bus.gateway.get_session_history", new_callable=AsyncMock, return_value=[]), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock), \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock) as mock_append, \
         patch.object(gw, "_run_agent", new_callable=AsyncMock, return_value="Hello back!"):

        # Put message and process
        msg = make_inbound("hello")
        await bus.publish_inbound(msg)

        # Run gateway briefly
        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    # Check outbound
    check("outbound not empty", not bus.outbound.empty())
    out = await bus.consume_outbound()
    check("outbound channel", out.channel == "discord")
    check("outbound chat_id", out.chat_id == "c1")
    check("outbound content", out.content == "Hello back!")

    # Check messages saved
    check("append_message called twice (user + assistant)", mock_append.call_count == 2)
    user_call = mock_append.call_args_list[0]
    check("user msg saved", user_call[0][1]["role"] == "user")
    assistant_call = mock_append.call_args_list[1]
    check("assistant msg saved", assistant_call[0][1]["role"] == "assistant")


asyncio.run(test_e2e())


# === Gateway: error handling ===

print("\n=== Gateway: error handling ===")


async def test_error_handling():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock,
               side_effect=RuntimeError("db down")):

        msg = make_inbound("trigger error")
        await bus.publish_inbound(msg)

        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    # Should send error response, not crash
    check("outbound has error message", not bus.outbound.empty())
    out = await bus.consume_outbound()
    check("error content", "error" in out.content.lower())
    check("error sent to correct channel", out.channel == "discord")


asyncio.run(test_error_handling())


# === Gateway: serial per-session processing ===

print("\n=== Gateway: serial per-session ===")


async def test_serial_per_session():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    processing_order = []
    processing_concurrent = []

    original_locks = {}

    async def mock_process(msg):
        key = msg.session_key
        # Track concurrent access
        if key not in original_locks:
            original_locks[key] = 0
        original_locks[key] += 1
        processing_concurrent.append(original_locks[key])
        processing_order.append(f"{key}:{msg.content}")
        await asyncio.sleep(0.05)
        original_locks[key] -= 1

    session = make_session()
    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, return_value=session), \
         patch("src.bus.gateway.get_session_history", new_callable=AsyncMock, return_value=[]), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock), \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock), \
         patch.object(gw, "_run_agent", new_callable=AsyncMock, return_value="ok"), \
         patch.object(gw, "_process_message", side_effect=mock_process):

        # Queue 3 messages for same session
        for i in range(3):
            await bus.publish_inbound(make_inbound(f"msg{i}", chat_id="c1"))

        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.5)
        gw._running = False
        await task

    check("all 3 processed", len(processing_order) == 3)
    # With per-session lock, concurrent access should always be 1
    check("serial (no concurrent access)", all(c == 1 for c in processing_concurrent))


asyncio.run(test_serial_per_session())


# === Gateway: cross-session concurrency ===

print("\n=== Gateway: cross-session concurrency ===")


async def test_cross_session():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    timestamps = {}

    async def slow_process(msg):
        key = msg.session_key
        timestamps[f"{key}:start"] = asyncio.get_event_loop().time()
        await asyncio.sleep(0.1)
        timestamps[f"{key}:end"] = asyncio.get_event_loop().time()

    session1 = make_session("discord:c1", 10)
    session2 = make_session("discord:c2", 20)

    async def mock_resolve(session_key, **kwargs):
        if "c2" in session_key:
            return session2
        return session1

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, side_effect=mock_resolve), \
         patch("src.bus.gateway.get_session_history", new_callable=AsyncMock, return_value=[]), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock), \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock), \
         patch.object(gw, "_run_agent", new_callable=AsyncMock, return_value="ok"), \
         patch.object(gw, "_process_message", side_effect=slow_process):

        # Queue messages for 2 different sessions
        await bus.publish_inbound(make_inbound("a", chat_id="c1"))
        await bus.publish_inbound(make_inbound("b", chat_id="c2"))

        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.4)
        gw._running = False
        await task

    check("both sessions processed", len(timestamps) == 4)
    # c2 should start before c1 finishes (concurrent)
    if len(timestamps) == 4:
        c2_start = timestamps.get("discord:c2:start", 999)
        c1_end = timestamps.get("discord:c1:end", 0)
        check("c2 started before c1 finished (concurrent)", c2_start < c1_end)


asyncio.run(test_cross_session())


# === Gateway: stop waits for in-flight tasks ===

print("\n=== Gateway: graceful stop ===")


async def test_stop():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)
    gw._running = True

    # Simulate active task
    async def long_task():
        await asyncio.sleep(0.1)

    task = asyncio.create_task(long_task())
    gw._active_tasks.add(task)
    task.add_done_callback(gw._active_tasks.discard)

    await gw.stop()
    check("running is False", gw._running is False)
    check("task completed", task.done())


asyncio.run(test_stop())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
