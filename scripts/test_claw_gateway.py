"""Unit tests for src/bus/gateway.py — dispatch via SessionRunner registry.

Rewritten 2026-04-11 for change `refactor-gateway-use-session-runner`: Gateway
no longer runs agents inline; it resolves a ChatSession, appends the user
message, obtains a SessionRunner from the registry, subscribes to the runner's
event stream, and waits for `done` before publishing one OutboundMessage with
the latest assistant text.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.bus.gateway import Gateway
from src.bus.message import InboundMessage
from src.models import ChatSession
from src.streaming.events import StreamEvent

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


def make_session(session_key="discord:c1", conv_id=10, sid=1):
    return ChatSession(
        id=sid, session_key=session_key, channel="discord", chat_id="c1",
        project_id=1, conversation_id=conv_id, mode="chat", status="active",
    )


def make_fake_runner(events: list[StreamEvent] | None = None) -> MagicMock:
    """Fake SessionRunner whose subscriber queue is pre-loaded with the given
    events. `add_subscriber` returns the queue; `remove_subscriber` /
    `notify_new_message` are spies."""
    runner = MagicMock()
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    for ev in events or []:
        queue.put_nowait(ev)
    runner.add_subscriber.return_value = queue
    runner.remove_subscriber = MagicMock()
    runner.notify_new_message = MagicMock()
    return runner


def make_stuck_runner() -> MagicMock:
    """A fake runner whose subscriber queue never receives any event —
    exercises the idle-timeout path."""
    runner = MagicMock()
    runner.add_subscriber.return_value = asyncio.Queue()
    runner.remove_subscriber = MagicMock()
    runner.notify_new_message = MagicMock()
    return runner


# === Gateway: end-to-end via SessionRunner ===

print("=== Gateway: end-to-end ===")


async def test_e2e():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1, role="assistant")

    session = make_session()
    runner = make_fake_runner(events=[
        StreamEvent(type="text_delta", content="Hello "),
        StreamEvent(type="text_delta", content="back!"),
        StreamEvent(type="done", finish_reason="stop"),
    ])

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, return_value=session), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock), \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock) as mock_append, \
         patch("src.bus.gateway.get_or_create_runner",
               new_callable=AsyncMock, return_value=runner):

        msg = make_inbound("hello")
        await bus.publish_inbound(msg)

        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    check("outbound not empty", not bus.outbound.empty())
    out = await bus.consume_outbound()
    check("outbound channel", out.channel == "discord")
    check("outbound chat_id", out.chat_id == "c1")
    check("outbound content", out.content == "Hello back!")

    # Gateway only writes the USER message; assistant message is written by the runner.
    check("append_message called once (user only)", mock_append.call_count == 1)
    user_call = mock_append.call_args_list[0]
    check("user msg saved", user_call[0][1]["role"] == "user")

    # Runner interactions
    check("runner.add_subscriber called", runner.add_subscriber.called)
    check("runner.notify_new_message called", runner.notify_new_message.called)
    check("runner.remove_subscriber called (finally)", runner.remove_subscriber.called)


asyncio.run(test_e2e())


# === Gateway: structured content list is flattened ===

print("\n=== Gateway: structured assistant content ===")


async def test_non_text_events_filtered():
    """tool_start / tool_end / usage events must NOT leak into the outbound;
    only text_delta contributes to the final reply."""
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    session = make_session()
    runner = make_fake_runner(events=[
        StreamEvent(type="text_delta", content="Let me check. "),
        StreamEvent(type="tool_start", tool_call_id="t1", name="read_file"),
        StreamEvent(type="tool_end"),
        StreamEvent(type="text_delta", content="Done."),
        StreamEvent(type="usage"),
        StreamEvent(type="done", finish_reason="stop"),
    ])

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, return_value=session), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock), \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock), \
         patch("src.bus.gateway.get_or_create_runner",
               new_callable=AsyncMock, return_value=runner):

        await bus.publish_inbound(make_inbound("hi"))
        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    check("outbound not empty", not bus.outbound.empty())
    out = await bus.consume_outbound()
    check("non-text events filtered out", out.content == "Let me check. Done.")


asyncio.run(test_non_text_events_filtered())


# === Gateway: empty turn falls back to placeholder ===

print("\n=== Gateway: empty turn ===")


async def test_empty_turn_placeholder():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    session = make_session()
    # done event with no preceding text_delta
    runner = make_fake_runner(events=[StreamEvent(type="done", finish_reason="stop")])

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, return_value=session), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock), \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock), \
         patch("src.bus.gateway.get_or_create_runner",
               new_callable=AsyncMock, return_value=runner):

        await bus.publish_inbound(make_inbound("hi"))
        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    out = await bus.consume_outbound()
    check("empty turn → placeholder", out.content == "(no response)")


asyncio.run(test_empty_turn_placeholder())


# === Gateway: error handling ===

print("\n=== Gateway: error handling ===")


async def test_error_handling():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    with patch("src.bus.gateway.resolve_session", new_callable=AsyncMock,
               side_effect=RuntimeError("db down")):

        await bus.publish_inbound(make_inbound("trigger error"))
        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    check("outbound has error message", not bus.outbound.empty())
    out = await bus.consume_outbound()
    check("error content", "error" in out.content.lower())
    check("error sent to correct channel", out.channel == "discord")


asyncio.run(test_error_handling())


# === Gateway: subscriber idle timeout ===

print("\n=== Gateway: subscriber timeout ===")


async def test_subscriber_timeout():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    session = make_session()
    runner = make_stuck_runner()

    # Shrink the idle-timeout constant for the test. The constant lives on the
    # module, not on the class, so we patch it module-wide.
    with patch("src.bus.gateway._BUS_SUBSCRIBER_TIMEOUT_SECONDS", 0.1), \
         patch("src.bus.gateway.resolve_session", new_callable=AsyncMock, return_value=session), \
         patch("src.bus.gateway.refresh_session", new_callable=AsyncMock) as mock_refresh, \
         patch("src.bus.gateway.append_message", new_callable=AsyncMock), \
         patch("src.bus.gateway.get_or_create_runner",
               new_callable=AsyncMock, return_value=runner):

        await bus.publish_inbound(make_inbound("slow"))
        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.3)
        gw._running = False
        await task

    check("no outbound on timeout", bus.outbound.empty())
    check("subscriber detached on timeout", runner.remove_subscriber.called)
    check("refresh_session NOT called on timeout", not mock_refresh.called)


asyncio.run(test_subscriber_timeout())


# === Gateway: /resume bypasses runner ===

print("\n=== Gateway: /resume bypass ===")


async def test_resume_bypass():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    with patch("src.bus.gateway.get_or_create_runner",
               new_callable=AsyncMock) as mock_get_runner, \
         patch.object(gw, "_handle_resume", new_callable=AsyncMock) as mock_handle_resume:

        await bus.publish_inbound(make_inbound("/resume run-abc"))
        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.15)
        gw._running = False
        await task

    check("_handle_resume called", mock_handle_resume.called)
    check("get_or_create_runner NOT called", not mock_get_runner.called)


asyncio.run(test_resume_bypass())


# === Gateway: cross-session concurrency ===

print("\n=== Gateway: cross-session concurrency ===")


async def test_cross_session():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)

    timestamps: dict[str, float] = {}

    async def slow_process(msg):
        key = msg.session_key
        timestamps[f"{key}:start"] = asyncio.get_event_loop().time()
        await asyncio.sleep(0.1)
        timestamps[f"{key}:end"] = asyncio.get_event_loop().time()

    with patch.object(gw, "_process_message", side_effect=slow_process):
        await bus.publish_inbound(make_inbound("a", chat_id="c1"))
        await bus.publish_inbound(make_inbound("b", chat_id="c2"))

        task = asyncio.create_task(gw.run())
        await asyncio.sleep(0.4)
        gw._running = False
        await task

    check("both sessions processed", len(timestamps) == 4)
    if len(timestamps) == 4:
        c2_start = timestamps.get("discord:c2:start", 999.0)
        c1_end = timestamps.get("discord:c1:end", 0.0)
        check("c2 started before c1 finished (concurrent)", c2_start < c1_end)


asyncio.run(test_cross_session())


# === Gateway: graceful stop ===

print("\n=== Gateway: graceful stop ===")


async def test_stop():
    bus = MessageBus()
    gw = Gateway(bus, project_id=1)
    gw._running = True

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
