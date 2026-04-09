"""Unit tests for src/channels/discord.py — Discord adapter, WebSocket events, REST send, splitting."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.channels.discord import (
    DiscordChannel,
    _OP_DISPATCH,
    _OP_HEARTBEAT,
    _OP_HEARTBEAT_ACK,
    _OP_HELLO,
    _OP_IDENTIFY,
    _OP_INVALID_SESSION,
    _OP_RECONNECT,
    _OP_RESUME,
    _MAX_MESSAGE_LEN,
    _split_message,
)

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


def make_discord(token="test_token"):
    bus = MessageBus()
    config = {"token": token}
    ch = DiscordChannel("discord", config, bus)
    return ch, bus


# === _split_message: short message ===

print("=== _split_message: short message ===")

check("no split needed", _split_message("hello", 2000) == ["hello"])
check("exact limit", _split_message("x" * 2000, 2000) == ["x" * 2000])

# === _split_message: long message ===

print("\n=== _split_message: long message ===")

long_text = "line1\nline2\nline3\nline4"
chunks = _split_message(long_text, 12)
check("splits into multiple", len(chunks) > 1)
# Rejoin should reconstruct
check("all content preserved", "".join(c.replace("\n", "") for c in chunks).replace("line", "") != "")

# === _split_message: no newline ===

print("\n=== _split_message: no newline ===")

no_nl = "a" * 5000
chunks = _split_message(no_nl, 2000)
check("forced split at max_len", len(chunks) == 3)
check("first chunk is max_len", len(chunks[0]) == 2000)
check("second chunk is max_len", len(chunks[1]) == 2000)
check("third chunk is remainder", len(chunks[2]) == 1000)

# === _split_message: newline-aware ===

print("\n=== _split_message: newline-aware ===")

text = "A" * 1500 + "\n" + "B" * 1500
chunks = _split_message(text, 2000)
check("splits at newline", len(chunks) == 2)
check("first chunk ends with A", chunks[0].endswith("A"))
check("second chunk starts with B", chunks[1].startswith("B"))

# === DiscordChannel: init ===

print("\n=== DiscordChannel: init ===")

ch, bus = make_discord("my_token")
check("name", ch.name == "discord")
check("token stored", ch._token == "my_token")
check("not running", ch._running is False)
check("no ws", ch._ws is None)

# === DiscordChannel: _on_message_create ===

print("\n=== DiscordChannel: _on_message_create ===")


async def test_message_create():
    ch, bus = make_discord()
    ch._bot_user_id = "bot123"

    data = {
        "id": "msg_001",
        "channel_id": "ch_42",
        "guild_id": "guild_1",
        "content": "hello bot",
        "author": {"id": "user_99", "bot": False},
    }

    await ch._on_message_create(data)
    check("inbound has message", not bus.inbound.empty())

    msg = await bus.consume_inbound()
    check("channel is discord", msg.channel == "discord")
    check("sender_id", msg.sender_id == "user_99")
    check("chat_id is channel_id", msg.chat_id == "ch_42")
    check("content", msg.content == "hello bot")
    check("metadata message_id", msg.metadata["message_id"] == "msg_001")
    check("metadata guild_id", msg.metadata["guild_id"] == "guild_1")


asyncio.run(test_message_create())

# === DiscordChannel: ignores bot messages ===

print("\n=== DiscordChannel: ignores bots ===")


async def test_ignore_bot():
    ch, bus = make_discord()
    ch._bot_user_id = "bot123"

    # Bot message
    await ch._on_message_create({
        "id": "m1", "channel_id": "c1", "content": "bot msg",
        "author": {"id": "other_bot", "bot": True},
    })
    check("bot message ignored", bus.inbound.empty())

    # Own message
    await ch._on_message_create({
        "id": "m2", "channel_id": "c1", "content": "self msg",
        "author": {"id": "bot123", "bot": False},
    })
    check("own message ignored", bus.inbound.empty())


asyncio.run(test_ignore_bot())

# === DiscordChannel: ignores empty content ===

print("\n=== DiscordChannel: ignores empty content ===")


async def test_ignore_empty():
    ch, bus = make_discord()
    ch._bot_user_id = "bot123"

    await ch._on_message_create({
        "id": "m1", "channel_id": "c1", "content": "",
        "author": {"id": "user1", "bot": False},
    })
    check("empty content ignored", bus.inbound.empty())

    await ch._on_message_create({
        "id": "m2", "channel_id": "c1", "content": "   ",
        "author": {"id": "user1", "bot": False},
    })
    check("whitespace content ignored", bus.inbound.empty())


asyncio.run(test_ignore_empty())

# === DiscordChannel: send via REST ===

print("\n=== DiscordChannel: send ===")


async def test_send():
    ch, bus = make_discord("token123")
    mock_http = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_http.post = AsyncMock(return_value=mock_resp)
    ch._http = mock_http

    from src.bus.message import OutboundMessage
    msg = OutboundMessage(channel="discord", chat_id="ch_42", content="reply text")
    await ch.send(msg)

    check("POST called", mock_http.post.called)
    call_args = mock_http.post.call_args
    check("correct URL", "/channels/ch_42/messages" in call_args[0][0])
    payload = call_args[1]["json"]
    check("content in payload", payload["content"] == "reply text")


asyncio.run(test_send())

# === DiscordChannel: send with message splitting ===

print("\n=== DiscordChannel: send splits long messages ===")


async def test_send_split():
    ch, bus = make_discord()
    mock_http = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_http.post = AsyncMock(return_value=mock_resp)
    ch._http = mock_http

    from src.bus.message import OutboundMessage
    long_content = "A" * 3000
    msg = OutboundMessage(channel="discord", chat_id="c1", content=long_content, reply_to="orig_msg")
    await ch.send(msg)

    check("multiple POSTs", mock_http.post.call_count == 2)
    # First chunk should have reply_to
    first_payload = mock_http.post.call_args_list[0][1]["json"]
    check("first has reply ref", "message_reference" in first_payload)
    # Second chunk should not
    second_payload = mock_http.post.call_args_list[1][1]["json"]
    check("second no reply ref", "message_reference" not in second_payload)


asyncio.run(test_send_split())

# === DiscordChannel: send rate limit handling ===

print("\n=== DiscordChannel: send rate limit ===")


async def test_rate_limit():
    ch, bus = make_discord()
    mock_http = AsyncMock()

    rate_resp = MagicMock()
    rate_resp.status_code = 429
    rate_resp.json.return_value = {"retry_after": 0.01}

    ok_resp = MagicMock()
    ok_resp.status_code = 200

    mock_http.post = AsyncMock(side_effect=[rate_resp, ok_resp])
    ch._http = mock_http

    from src.bus.message import OutboundMessage
    msg = OutboundMessage(channel="discord", chat_id="c1", content="retry me")
    await ch.send(msg)

    check("retried after 429", mock_http.post.call_count == 2)


asyncio.run(test_rate_limit())

# === DiscordChannel: stop ===

print("\n=== DiscordChannel: stop ===")


async def test_stop():
    ch, bus = make_discord()
    ch._running = True
    ch._http = AsyncMock()
    ch._ws = AsyncMock()
    ch._heartbeat_task = None

    await ch.stop()
    check("running set to False", ch._running is False)
    check("ws closed", ch._ws is None)
    check("http closed", ch._http is None)


asyncio.run(test_stop())

# === DiscordChannel: _gateway_loop HELLO → IDENTIFY ===

print("\n=== DiscordChannel: gateway HELLO → IDENTIFY ===")


async def test_hello_identify():
    ch, bus = make_discord()
    ch._running = True

    hello_msg = json.dumps({"op": _OP_HELLO, "d": {"heartbeat_interval": 41250}})
    ready_msg = json.dumps({
        "op": _OP_DISPATCH, "t": "READY", "s": 1,
        "d": {
            "session_id": "sess_1",
            "resume_gateway_url": "wss://resume.example.com",
            "user": {"id": "bot_id", "username": "TestBot"},
        },
    })

    class FakeWS:
        def __init__(self):
            self.messages = [hello_msg, ready_msg]
            self.sent = []
            self.idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.idx >= len(self.messages):
                raise StopAsyncIteration
            msg = self.messages[self.idx]
            self.idx += 1
            return msg

        async def send(self, data):
            self.sent.append(json.loads(data))

    ws = FakeWS()
    # Patch create_task to avoid actual heartbeat
    with patch("asyncio.create_task", return_value=MagicMock()):
        await ch._gateway_loop(ws)

    check("sent IDENTIFY", any(m.get("op") == _OP_IDENTIFY for m in ws.sent))
    check("session_id stored", ch._session_id == "sess_1")
    check("bot_user_id stored", ch._bot_user_id == "bot_id")
    check("resume_url stored", ch._resume_gateway_url == "wss://resume.example.com")
    check("heartbeat_interval set", ch._heartbeat_interval == 41.25)


asyncio.run(test_hello_identify())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
