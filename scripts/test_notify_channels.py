"""Unit tests for SseChannel + WechatChannel + DiscordChannel."""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from src.notify.channels.discord import DiscordChannel
from src.notify.channels.sse import SseChannel
from src.notify.channels.wechat import WechatChannel
from src.notify.events import Notification

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def _notif(user_id: int = 1, event_type: str = "run_failed") -> Notification:
    return Notification(
        event_type=event_type,
        user_id=user_id,
        title="t",
        body="b",
        payload={"k": "v"},
    )


async def test_sse_register_and_deliver() -> None:
    print("\n-- SseChannel register + deliver --")
    sse = SseChannel()
    q = sse.register(1)
    await sse.deliver(_notif(1))
    check("queue received one notification", q.qsize() == 1)
    got = q.get_nowait()
    check("notification payload intact", got.user_id == 1 and got.title == "t")


async def test_sse_fanout_multi_tab() -> None:
    print("\n-- SseChannel fan-out to multi-tab --")
    sse = SseChannel()
    q1 = sse.register(1)
    q2 = sse.register(1)
    await sse.deliver(_notif(1))
    check("both queues received", q1.qsize() == 1 and q2.qsize() == 1)


async def test_sse_noop_on_unknown_user() -> None:
    print("\n-- SseChannel noop on user with no connections --")
    sse = SseChannel()
    sse.register(1)
    await sse.deliver(_notif(99))
    check("no exception raised", True)


async def test_sse_unregister() -> None:
    print("\n-- SseChannel unregister --")
    sse = SseChannel()
    q = sse.register(1)
    sse.unregister(1, q)
    await sse.deliver(_notif(1))
    check("queue not modified after unregister", q.qsize() == 0)
    check("user list cleaned up", 1 not in sse._queues)


async def test_sse_drop_oldest() -> None:
    print("\n-- SseChannel drop-oldest on full queue --")
    sse = SseChannel(default_max_size=2)
    q = sse.register(1)
    for i in range(3):
        await sse.deliver(
            Notification(
                event_type="agent_progress",
                user_id=1,
                title=f"t{i}",
                body="",
                payload={},
            )
        )
    check("queue capped at 2", q.qsize() == 2)
    first = q.get_nowait()
    check("oldest dropped, next is t1", first.title == "t1")


def _mock_client(status_code: int = 200, raise_exc: Exception | None = None):
    client = MagicMock()
    if raise_exc is not None:
        client.post = AsyncMock(side_effect=raise_exc)
    else:
        response = MagicMock()
        response.status_code = status_code
        client.post = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    return client


async def test_wechat_success() -> None:
    print("\n-- WechatChannel success --")
    ch = WechatChannel("https://example.com/wechat")
    ch._client = _mock_client(200)
    await ch.deliver(_notif())
    check("post called once", ch._client.post.await_count == 1)
    args, kwargs = ch._client.post.call_args
    body = kwargs.get("json") or (args[1] if len(args) > 1 else None)
    check("body has markdown msgtype", body is not None and body["msgtype"] == "markdown")


async def test_wechat_404_logged_not_raised() -> None:
    print("\n-- WechatChannel 404 --")
    ch = WechatChannel("https://example.com/wechat")
    ch._client = _mock_client(404)
    try:
        await ch.deliver(_notif())
        check("did not raise on 404", True)
    except Exception as exc:
        check("did not raise on 404", False, str(exc))


async def test_wechat_timeout() -> None:
    print("\n-- WechatChannel timeout --")
    ch = WechatChannel("https://example.com/wechat")
    ch._client = _mock_client(raise_exc=httpx.TimeoutException("boom"))
    try:
        await ch.deliver(_notif())
        check("timeout absorbed", True)
    except Exception as exc:
        check("timeout absorbed", False, str(exc))


async def test_discord_success() -> None:
    print("\n-- DiscordChannel success --")
    ch = DiscordChannel("https://example.com/discord")
    ch._client = _mock_client(200)
    await ch.deliver(_notif())
    check("post called once", ch._client.post.await_count == 1)
    args, kwargs = ch._client.post.call_args
    body = kwargs.get("json") or (args[1] if len(args) > 1 else None)
    check("body has content + username", body is not None and "content" in body and body["username"] == "mas-pipeline")


async def test_discord_500() -> None:
    print("\n-- DiscordChannel 500 --")
    ch = DiscordChannel("https://example.com/discord")
    ch._client = _mock_client(500)
    try:
        await ch.deliver(_notif())
        check("500 absorbed", True)
    except Exception as exc:
        check("500 absorbed", False, str(exc))


async def test_discord_network_error() -> None:
    print("\n-- DiscordChannel network error --")
    ch = DiscordChannel("https://example.com/discord")
    ch._client = _mock_client(raise_exc=httpx.ConnectError("no route"))
    try:
        await ch.deliver(_notif())
        check("connect error absorbed", True)
    except Exception as exc:
        check("connect error absorbed", False, str(exc))


async def main() -> int:
    await test_sse_register_and_deliver()
    await test_sse_fanout_multi_tab()
    await test_sse_noop_on_unknown_user()
    await test_sse_unregister()
    await test_sse_drop_oldest()
    await test_wechat_success()
    await test_wechat_404_logged_not_raised()
    await test_wechat_timeout()
    await test_discord_success()
    await test_discord_500()
    await test_discord_network_error()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
