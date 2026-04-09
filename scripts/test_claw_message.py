"""Unit tests for src/bus/message.py — InboundMessage, OutboundMessage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


# === InboundMessage fields ===

print("=== InboundMessage: field access ===")

msg = InboundMessage(
    channel="discord",
    sender_id="user123",
    chat_id="ch456",
    content="hello",
)
check("channel", msg.channel == "discord")
check("sender_id", msg.sender_id == "user123")
check("chat_id", msg.chat_id == "ch456")
check("content", msg.content == "hello")
check("metadata default empty dict", msg.metadata == {})

# === InboundMessage session_key ===

print("\n=== InboundMessage: session_key ===")

check("session_key format", msg.session_key == "discord:ch456")

msg2 = InboundMessage(channel="qq", sender_id="s", chat_id="g789", content="x")
check("session_key qq", msg2.session_key == "qq:g789")

msg3 = InboundMessage(channel="wechat", sender_id="s", chat_id="wx_abc", content="x")
check("session_key wechat", msg3.session_key == "wechat:wx_abc")

# === InboundMessage with metadata ===

print("\n=== InboundMessage: metadata ===")

msg_meta = InboundMessage(
    channel="discord",
    sender_id="u1",
    chat_id="c1",
    content="hi",
    metadata={"message_id": "12345", "guild_id": "g1"},
)
check("metadata preserved", msg_meta.metadata["message_id"] == "12345")
check("metadata guild_id", msg_meta.metadata["guild_id"] == "g1")

# === OutboundMessage fields ===

print("\n=== OutboundMessage: field access ===")

out = OutboundMessage(
    channel="discord",
    chat_id="ch456",
    content="response text",
)
check("channel", out.channel == "discord")
check("chat_id", out.chat_id == "ch456")
check("content", out.content == "response text")
check("reply_to default None", out.reply_to is None)
check("metadata default empty dict", out.metadata == {})

# === OutboundMessage with reply_to ===

print("\n=== OutboundMessage: reply_to ===")

out2 = OutboundMessage(
    channel="qq",
    chat_id="g1",
    content="reply",
    reply_to="msg_999",
    metadata={"seq": 42},
)
check("reply_to", out2.reply_to == "msg_999")
check("metadata", out2.metadata["seq"] == 42)

# === Dataclass independence ===

print("\n=== Dataclass: independence ===")

a = InboundMessage(channel="a", sender_id="s", chat_id="c", content="x")
b = InboundMessage(channel="b", sender_id="s", chat_id="c", content="x")
check("different instances", a is not b)
check("different channels", a.channel != b.channel)
check("different session_keys", a.session_key != b.session_key)

# Metadata isolation
m1 = InboundMessage(channel="a", sender_id="s", chat_id="c", content="x")
m2 = InboundMessage(channel="a", sender_id="s", chat_id="c", content="x")
m1.metadata["key"] = "val"
check("metadata isolated", "key" not in m2.metadata)


print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
