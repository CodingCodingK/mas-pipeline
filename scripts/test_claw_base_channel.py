"""Unit tests for src/channels/base.py — BaseChannel._handle_message."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.bus.message import OutboundMessage
from src.channels.base import BaseChannel

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


class StubChannel(BaseChannel):
    """Concrete channel for testing the base class."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


# === BaseChannel: init ===

print("=== BaseChannel: init ===")

bus = MessageBus()
ch = StubChannel(name="test", config={"key": "val"}, bus=bus)
check("name property", ch.name == "test")
check("config stored", ch._config == {"key": "val"})
check("bus stored", ch._bus is bus)


# === _handle_message: publishes InboundMessage ===

print("\n=== _handle_message: publishes InboundMessage ===")


async def test_handle_message():
    bus = MessageBus()
    ch = StubChannel(name="discord", config={}, bus=bus)

    await ch._handle_message(
        sender_id="user_42",
        chat_id="channel_99",
        content="hello world",
    )

    check("inbound not empty", not bus.inbound.empty())

    msg = await bus.consume_inbound()
    check("channel set to adapter name", msg.channel == "discord")
    check("sender_id as string", msg.sender_id == "user_42")
    check("chat_id as string", msg.chat_id == "channel_99")
    check("content preserved", msg.content == "hello world")
    check("metadata empty by default", msg.metadata == {})


asyncio.run(test_handle_message())


# === _handle_message: metadata forwarded ===

print("\n=== _handle_message: metadata forwarded ===")


async def test_handle_message_metadata():
    bus = MessageBus()
    ch = StubChannel(name="qq", config={}, bus=bus)

    await ch._handle_message(
        sender_id="s1",
        chat_id="g1",
        content="hi",
        metadata={"message_id": "m123", "group_openid": "g1"},
    )

    msg = await bus.consume_inbound()
    check("metadata message_id", msg.metadata["message_id"] == "m123")
    check("metadata group_openid", msg.metadata["group_openid"] == "g1")


asyncio.run(test_handle_message_metadata())


# === _handle_message: sender_id/chat_id coerced to str ===

print("\n=== _handle_message: type coercion ===")


async def test_type_coercion():
    bus = MessageBus()
    ch = StubChannel(name="wechat", config={}, bus=bus)

    await ch._handle_message(
        sender_id=12345,
        chat_id=67890,
        content="numeric ids",
    )

    msg = await bus.consume_inbound()
    check("sender_id is str", isinstance(msg.sender_id, str))
    check("sender_id value", msg.sender_id == "12345")
    check("chat_id is str", isinstance(msg.chat_id, str))
    check("chat_id value", msg.chat_id == "67890")


asyncio.run(test_type_coercion())


# === _handle_message: None metadata → empty dict ===

print("\n=== _handle_message: None metadata ===")


async def test_none_metadata():
    bus = MessageBus()
    ch = StubChannel(name="test", config={}, bus=bus)

    await ch._handle_message("s", "c", "text", metadata=None)

    msg = await bus.consume_inbound()
    check("None metadata → empty dict", msg.metadata == {})


asyncio.run(test_none_metadata())


# === Multiple messages accumulate in queue ===

print("\n=== Multiple messages ===")


async def test_multiple():
    bus = MessageBus()
    ch = StubChannel(name="test", config={}, bus=bus)

    for i in range(3):
        await ch._handle_message("s", "c", f"msg_{i}")

    check("queue has 3", bus.inbound.qsize() == 3)
    for i in range(3):
        msg = await bus.consume_inbound()
        check(f"msg_{i} content", msg.content == f"msg_{i}")


asyncio.run(test_multiple())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
