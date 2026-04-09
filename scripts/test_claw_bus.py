"""Unit tests for src/bus/bus.py — MessageBus publish/consume, FIFO order, blocking."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.bus.message import InboundMessage, OutboundMessage

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


def make_inbound(content: str = "hi", channel: str = "discord") -> InboundMessage:
    return InboundMessage(channel=channel, sender_id="u1", chat_id="c1", content=content)


def make_outbound(content: str = "reply", channel: str = "discord") -> OutboundMessage:
    return OutboundMessage(channel=channel, chat_id="c1", content=content)


# === MessageBus: init ===

print("=== MessageBus: init ===")

bus = MessageBus()
check("inbound queue exists", bus.inbound is not None)
check("outbound queue exists", bus.outbound is not None)
check("inbound empty", bus.inbound.empty())
check("outbound empty", bus.outbound.empty())


# === Inbound: publish and consume ===

print("\n=== Inbound: publish and consume ===")


async def test_inbound_basic():
    bus = MessageBus()
    msg = make_inbound("hello")
    await bus.publish_inbound(msg)
    check("inbound not empty after publish", not bus.inbound.empty())

    got = await bus.consume_inbound()
    check("consumed same message", got is msg)
    check("content preserved", got.content == "hello")
    check("inbound empty after consume", bus.inbound.empty())


asyncio.run(test_inbound_basic())


# === Outbound: publish and consume ===

print("\n=== Outbound: publish and consume ===")


async def test_outbound_basic():
    bus = MessageBus()
    msg = make_outbound("response")
    await bus.publish_outbound(msg)
    got = await bus.consume_outbound()
    check("outbound same message", got is msg)
    check("outbound content", got.content == "response")
    check("outbound empty after consume", bus.outbound.empty())


asyncio.run(test_outbound_basic())


# === FIFO order ===

print("\n=== FIFO order ===")


async def test_fifo():
    bus = MessageBus()
    msgs = [make_inbound(f"msg_{i}") for i in range(5)]
    for m in msgs:
        await bus.publish_inbound(m)

    results = []
    for _ in range(5):
        results.append(await bus.consume_inbound())

    check("FIFO order preserved", [r.content for r in results] == [f"msg_{i}" for i in range(5)])


asyncio.run(test_fifo())


# === Blocking behavior: consume blocks until publish ===

print("\n=== Blocking behavior ===")


async def test_blocking():
    bus = MessageBus()
    consumed = []

    async def consumer():
        consumed.append(await bus.consume_inbound())

    task = asyncio.create_task(consumer())
    # Consumer should be blocked
    await asyncio.sleep(0.05)
    check("consumer blocked (no result yet)", len(consumed) == 0)

    # Now publish
    await bus.publish_inbound(make_inbound("unblock"))
    await asyncio.sleep(0.05)
    check("consumer unblocked", len(consumed) == 1)
    check("got correct message", consumed[0].content == "unblock")
    await task


asyncio.run(test_blocking())


# === Timeout on consume (with wait_for) ===

print("\n=== Consume with timeout ===")


async def test_timeout():
    bus = MessageBus()
    timed_out = False
    try:
        await asyncio.wait_for(bus.consume_inbound(), timeout=0.05)
    except TimeoutError:
        timed_out = True
    check("timeout fires on empty queue", timed_out)


asyncio.run(test_timeout())


# === Independent queues ===

print("\n=== Independent queues ===")


async def test_independent():
    bus = MessageBus()
    await bus.publish_inbound(make_inbound("in"))
    await bus.publish_outbound(make_outbound("out"))

    check("inbound has 1", bus.inbound.qsize() == 1)
    check("outbound has 1", bus.outbound.qsize() == 1)

    got_in = await bus.consume_inbound()
    check("inbound consumed correctly", got_in.content == "in")
    check("outbound still has 1", bus.outbound.qsize() == 1)


asyncio.run(test_independent())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
