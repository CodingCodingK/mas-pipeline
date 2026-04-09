"""Unit tests for src/channels/wechat.py — WeChat adapter, long-poll, send, token persistence."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.bus.message import OutboundMessage
from src.channels.wechat import WeChatChannel, _split_message

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


def make_wechat(token="test_token", state_dir=None):
    bus = MessageBus()
    config = {
        "token": token,
        "base_url": "https://fake.weixin.qq.com",
        "state_dir": state_dir or tempfile.mkdtemp(),
    }
    ch = WeChatChannel("wechat", config, bus)
    return ch, bus


# === _split_message: short ===

print("=== _split_message: short ===")

check("no split", _split_message("hello", 4000) == ["hello"])
check("exact limit", _split_message("x" * 4000, 4000) == ["x" * 4000])

# === _split_message: long ===

print("\n=== _split_message: long ===")

long_text = "A" * 10000
chunks = _split_message(long_text, 4000)
check("3 chunks", len(chunks) == 3)
check("first 4000", len(chunks[0]) == 4000)
check("second 4000", len(chunks[1]) == 4000)
check("third 2000", len(chunks[2]) == 2000)

# === _split_message: newline-aware ===

print("\n=== _split_message: newline-aware ===")

text = "A" * 3000 + "\n" + "B" * 3000
chunks = _split_message(text, 4000)
check("splits at newline", len(chunks) == 2)
check("first chunk ends with A", chunks[0].endswith("A"))

# === WeChatChannel: init ===

print("\n=== WeChatChannel: init ===")

ch, bus = make_wechat("my_token")
check("name", ch.name == "wechat")
check("token", ch._token == "my_token")
check("base_url", ch._base_url == "https://fake.weixin.qq.com")
check("not running", ch._running is False)
check("context_tokens empty", len(ch._context_tokens) == 0)

# === _process_message: text message ===

print("\n=== _process_message: text message ===")


async def test_process_text():
    ch, bus = make_wechat()

    msg_data = {
        "from_user_id": "wx_user_1",
        "context_token": "ctx_abc",
        "message_id": "msg_001",
        "seq": 42,
        "item_list": [
            {"type": 1, "text_item": {"content": "hello wechat"}},
        ],
    }

    await ch._process_message(msg_data)

    check("inbound has message", not bus.inbound.empty())
    inbound = await bus.consume_inbound()
    check("channel is wechat", inbound.channel == "wechat")
    check("sender_id", inbound.sender_id == "wx_user_1")
    check("chat_id = from_user_id", inbound.chat_id == "wx_user_1")
    check("content", inbound.content == "hello wechat")
    check("context_token cached", ch._context_tokens.get("wx_user_1") == "ctx_abc")


asyncio.run(test_process_text())

# === _process_message: multi-text items concatenated ===

print("\n=== _process_message: multi-text ===")


async def test_multi_text():
    ch, bus = make_wechat()

    msg_data = {
        "from_user_id": "wx_user_2",
        "context_token": "ctx_def",
        "item_list": [
            {"type": 1, "text_item": {"content": "line 1"}},
            {"type": 1, "text_item": {"content": "line 2"}},
        ],
    }

    await ch._process_message(msg_data)
    inbound = await bus.consume_inbound()
    check("lines joined with newline", inbound.content == "line 1\nline 2")


asyncio.run(test_multi_text())

# === _process_message: non-text items ignored ===

print("\n=== _process_message: non-text ignored ===")


async def test_non_text():
    ch, bus = make_wechat()

    msg_data = {
        "from_user_id": "wx_user_3",
        "item_list": [
            {"type": 2, "image_item": {"url": "http://img.example.com"}},
        ],
    }

    await ch._process_message(msg_data)
    check("non-text message ignored", bus.inbound.empty())


asyncio.run(test_non_text())

# === _process_message: empty content ignored ===

print("\n=== _process_message: empty ignored ===")


async def test_empty_content():
    ch, bus = make_wechat()

    msg_data = {
        "from_user_id": "wx_user_4",
        "item_list": [
            {"type": 1, "text_item": {"content": ""}},
        ],
    }

    await ch._process_message(msg_data)
    check("empty text ignored", bus.inbound.empty())


asyncio.run(test_empty_content())

# === send: with context_token ===

print("\n=== send: with context_token ===")


async def test_send():
    ch, bus = make_wechat()
    ch._context_tokens["wx_user_1"] = "ctx_123"
    mock_http = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_http.post = AsyncMock(return_value=mock_resp)
    ch._http = mock_http

    msg = OutboundMessage(channel="wechat", chat_id="wx_user_1", content="reply text")
    await ch.send(msg)

    check("POST called", mock_http.post.called)
    call_args = mock_http.post.call_args
    check("correct URL", "/ilink/bot/sendmessage" in call_args[0][0])

    payload = call_args[1]["json"]
    check("to_user_id", payload["to_user_id"] == "wx_user_1")
    check("context_token", payload["context_token"] == "ctx_123")
    check("item_list has text", payload["item_list"][0]["type"] == 1)
    check("text content", payload["item_list"][0]["text_item"]["content"] == "reply text")


asyncio.run(test_send())

# === send: no context_token ===

print("\n=== send: no context_token ===")


async def test_send_no_ctx():
    ch, bus = make_wechat()
    ch._http = AsyncMock()

    msg = OutboundMessage(channel="wechat", chat_id="unknown_user", content="no ctx")
    await ch.send(msg)

    check("no POST when no context_token", not ch._http.post.called)


asyncio.run(test_send_no_ctx())

# === send: message splitting ===

print("\n=== send: message splitting ===")


async def test_send_split():
    ch, bus = make_wechat()
    ch._context_tokens["wx_u"] = "ctx"
    mock_http = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_http.post = AsyncMock(return_value=mock_resp)
    ch._http = mock_http

    msg = OutboundMessage(channel="wechat", chat_id="wx_u", content="A" * 10000)
    await ch.send(msg)

    check("3 POSTs for 10000 chars", mock_http.post.call_count == 3)


asyncio.run(test_send_split())

# === _auth_headers ===

print("\n=== _auth_headers ===")

ch, _ = make_wechat("bearer_tok")
headers = ch._auth_headers()
check("Authorization header", headers["Authorization"] == "Bearer bearer_tok")
check("AuthorizationType", headers["AuthorizationType"] == "ilink_bot_token")
check("Content-Type", headers["Content-Type"] == "application/json")

# === Token persistence: save and load ===

print("\n=== Token persistence ===")

tmp_dir = tempfile.mkdtemp()


def test_persistence():
    ch1, _ = make_wechat("save_token", state_dir=tmp_dir)
    ch1._get_updates_buf = "cursor_123"
    ch1._context_tokens = {"wx_u1": "ctx_1", "wx_u2": "ctx_2"}
    ch1._save_state()

    state_file = Path(tmp_dir) / "account.json"
    check("state file created", state_file.exists())

    data = json.loads(state_file.read_text(encoding="utf-8"))
    check("token saved", data["token"] == "save_token")
    check("buf saved", data["get_updates_buf"] == "cursor_123")
    check("context_tokens saved", data["context_tokens"]["wx_u1"] == "ctx_1")

    # Load into new channel (token="" to test loading)
    ch2, _ = make_wechat("", state_dir=tmp_dir)
    check("token loaded", ch2._token == "save_token")
    check("buf loaded", ch2._get_updates_buf == "cursor_123")
    check("context_tokens loaded", ch2._context_tokens.get("wx_u1") == "ctx_1")


test_persistence()

# === _poll_once: parses response ===

print("\n=== _poll_once ===")


async def test_poll_once():
    ch, bus = make_wechat()
    mock_http = AsyncMock()

    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {
        "buf": "new_cursor",
        "msgs": [
            {
                "from_user_id": "wx_poll_user",
                "context_token": "ctx_poll",
                "message_id": "pm_1",
                "item_list": [{"type": 1, "text_item": {"content": "polled message"}}],
            },
        ],
    }
    mock_http.post = AsyncMock(return_value=poll_resp)
    ch._http = mock_http

    await ch._poll_once()

    check("buf updated", ch._get_updates_buf == "new_cursor")
    check("inbound has message", not bus.inbound.empty())
    inbound = await bus.consume_inbound()
    check("content from poll", inbound.content == "polled message")
    check("context_token cached", ch._context_tokens.get("wx_poll_user") == "ctx_poll")


asyncio.run(test_poll_once())

# === stop ===

print("\n=== stop ===")


async def test_stop():
    tmp = tempfile.mkdtemp()
    ch, _ = make_wechat("tok", state_dir=tmp)
    ch._running = True
    ch._http = AsyncMock()

    await ch.stop()
    check("running False", ch._running is False)
    check("http closed", ch._http is None)
    # State should be saved on stop
    check("state file saved", (Path(tmp) / "account.json").exists())


asyncio.run(test_stop())


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
