"""Unit tests for src/channels/qq.py — QQ adapter, C2C + group events, dedup, send routing."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Mock botpy before importing QQChannel
sys.modules["botpy"] = MagicMock()

from src.bus.bus import MessageBus
from src.bus.message import OutboundMessage
from src.channels.qq import QQChannel, _DEDUP_CACHE_SIZE

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


def make_qq():
    bus = MessageBus()
    config = {"app_id": "app123", "secret": "secret456"}
    # Patch _QQBotClient to avoid real botpy init
    with patch("src.channels.qq._QQBotClient"):
        ch = QQChannel("qq", config, bus)
    return ch, bus


def make_c2c_message(msg_id="m1", user_openid="user_1", content="hello"):
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.author = MagicMock()
    msg.author.user_openid = user_openid
    msg.author.id = user_openid
    return msg


def make_group_message(msg_id="m2", member_openid="user_2", group_openid="grp_1", content="hi"):
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.group_openid = group_openid
    msg.author = MagicMock()
    msg.author.member_openid = member_openid
    msg.author.id = member_openid
    return msg


# === QQChannel: init ===

print("=== QQChannel: init ===")

ch, bus = make_qq()
check("name", ch.name == "qq")
check("app_id", ch._app_id == "app123")
check("secret", ch._secret == "secret456")
check("dedup empty", len(ch._seen_ids) == 0)
check("chat_type_cache empty", len(ch._chat_type_cache) == 0)

# === handle_c2c: processes C2C message ===

print("\n=== handle_c2c ===")


async def test_c2c():
    ch, bus = make_qq()
    msg = make_c2c_message("msg_001", "user_A", "hello from c2c")
    await ch.handle_c2c(msg)

    check("inbound has message", not bus.inbound.empty())
    inbound = await bus.consume_inbound()
    check("channel is qq", inbound.channel == "qq")
    check("sender_id", inbound.sender_id == "user_A")
    check("chat_id = sender for c2c", inbound.chat_id == "user_A")
    check("content", inbound.content == "hello from c2c")
    check("chat_type cached as c2c", ch._chat_type_cache.get("user_A") == "c2c")


asyncio.run(test_c2c())

# === handle_group_at: processes group @mention ===

print("\n=== handle_group_at ===")


async def test_group():
    ch, bus = make_qq()
    msg = make_group_message("msg_002", "user_B", "grp_X", "hello from group")
    await ch.handle_group_at(msg)

    check("inbound has message", not bus.inbound.empty())
    inbound = await bus.consume_inbound()
    check("sender_id", inbound.sender_id == "user_B")
    check("chat_id = group_openid", inbound.chat_id == "grp_X")
    check("content", inbound.content == "hello from group")
    check("chat_type cached as group", ch._chat_type_cache.get("grp_X") == "group")
    check("metadata has group_openid", inbound.metadata.get("group_openid") == "grp_X")


asyncio.run(test_group())

# === Deduplication ===

print("\n=== Deduplication ===")


async def test_dedup():
    ch, bus = make_qq()
    msg = make_c2c_message("dup_001", "user_C", "first")
    await ch.handle_c2c(msg)

    check("first message accepted", not bus.inbound.empty())
    await bus.consume_inbound()

    # Send same message ID again
    msg2 = make_c2c_message("dup_001", "user_C", "duplicate")
    await ch.handle_c2c(msg2)
    check("duplicate rejected", bus.inbound.empty())

    # Different ID is accepted
    msg3 = make_c2c_message("dup_002", "user_C", "different")
    await ch.handle_c2c(msg3)
    check("different ID accepted", not bus.inbound.empty())


asyncio.run(test_dedup())

# === Dedup LRU eviction ===

print("\n=== Dedup: LRU eviction ===")

ch, _ = make_qq()
for i in range(_DEDUP_CACHE_SIZE + 5):
    ch._is_duplicate(f"id_{i}")
check("cache capped", len(ch._seen_ids) == _DEDUP_CACHE_SIZE)
check("oldest evicted", "id_0" not in ch._seen_ids)
check("newest kept", f"id_{_DEDUP_CACHE_SIZE + 4}" in ch._seen_ids)

# === Empty content ignored ===

print("\n=== Empty content ignored ===")


async def test_empty():
    ch, bus = make_qq()
    msg = make_c2c_message("m_empty", "user_D", "")
    await ch.handle_c2c(msg)
    check("empty c2c ignored", bus.inbound.empty())

    msg2 = make_c2c_message("m_space", "user_D", "   ")
    await ch.handle_c2c(msg2)
    check("whitespace c2c ignored", bus.inbound.empty())


asyncio.run(test_empty())

# === send: routes to c2c ===

print("\n=== send: c2c routing ===")


async def test_send_c2c():
    ch, bus = make_qq()
    ch._chat_type_cache["user_X"] = "c2c"

    mock_api = AsyncMock()
    ch._client = MagicMock()
    ch._client.api = mock_api

    out = OutboundMessage(channel="qq", chat_id="user_X", content="reply")
    await ch.send(out)

    check("post_c2c_message called", mock_api.post_c2c_message.called)
    call_kw = mock_api.post_c2c_message.call_args[1]
    check("openid correct", call_kw["openid"] == "user_X")
    check("content correct", call_kw["content"] == "reply")


asyncio.run(test_send_c2c())

# === send: routes to group ===

print("\n=== send: group routing ===")


async def test_send_group():
    ch, bus = make_qq()
    ch._chat_type_cache["grp_Y"] = "group"

    mock_api = AsyncMock()
    ch._client = MagicMock()
    ch._client.api = mock_api

    out = OutboundMessage(channel="qq", chat_id="grp_Y", content="group reply")
    await ch.send(out)

    check("post_group_message called", mock_api.post_group_message.called)
    call_kw = mock_api.post_group_message.call_args[1]
    check("group_openid correct", call_kw["group_openid"] == "grp_Y")


asyncio.run(test_send_group())

# === send: defaults to c2c when unknown ===

print("\n=== send: default to c2c ===")


async def test_send_default():
    ch, bus = make_qq()
    # No entry in chat_type_cache

    mock_api = AsyncMock()
    ch._client = MagicMock()
    ch._client.api = mock_api

    out = OutboundMessage(channel="qq", chat_id="unknown_id", content="default")
    await ch.send(out)

    check("defaults to c2c", mock_api.post_c2c_message.called)


asyncio.run(test_send_default())

# === send: no client ready ===

print("\n=== send: no client ===")


async def test_send_no_client():
    ch, bus = make_qq()
    ch._client = None

    out = OutboundMessage(channel="qq", chat_id="x", content="nope")
    # Should not raise
    await ch.send(out)
    check("no error when client is None", True)


asyncio.run(test_send_no_client())

# === stop ===

print("\n=== stop ===")


async def test_stop():
    ch, bus = make_qq()
    ch._running = True
    ch._client = MagicMock()
    ch._client.close = AsyncMock()
    ch._task = MagicMock()
    ch._task.done.return_value = True

    await ch.stop()
    check("running False", ch._running is False)


asyncio.run(test_stop())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
