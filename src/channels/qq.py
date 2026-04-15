"""QQ channel adapter: official qq-botpy SDK integration."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any

from src.bus.message import OutboundMessage
from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_DEDUP_CACHE_SIZE = 1000


class QQChannel(BaseChannel):
    """QQ bot via official qq-botpy SDK."""

    def __init__(self, name: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(name, config, bus)
        self._app_id = config["app_id"]
        self._secret = config["secret"]
        self._client: Any = None
        self._api: Any = None
        self._msg_seq = 0
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._chat_type_cache: dict[str, str] = {}  # chat_id -> "c2c" | "group"
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        import botpy
        from botpy import BotAPI

        self._running = True
        intents = botpy.Intents(public_messages=True, direct_message=True)
        self._client = _QQBotClient(
            intents=intents,
            channel=self,
        )
        # Run botpy in background task (it blocks)
        self._task = asyncio.create_task(self._run_client())

    async def _run_client(self) -> None:
        try:
            await self._client.start(appid=self._app_id, secret=self._secret)
        except Exception:
            if self._running:
                logger.exception("QQ client stopped unexpectedly")

    async def stop(self) -> None:
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()

    async def send(self, msg: OutboundMessage) -> None:
        if not self._client or not self._client.api:
            logger.warning("QQ client not ready, cannot send")
            return
        if msg.attachments:
            logger.warning(
                "QQ channel does not support attachments; dropping %d file(s) on message to %s",
                len(msg.attachments), msg.chat_id,
            )

        api = self._client.api
        self._msg_seq += 1
        chat_type = self._chat_type_cache.get(msg.chat_id, "c2c")

        try:
            if chat_type == "group":
                await api.post_group_message(
                    group_openid=msg.chat_id,
                    msg_type=0,
                    msg_seq=self._msg_seq,
                    content=msg.content,
                )
            else:
                await api.post_c2c_message(
                    openid=msg.chat_id,
                    msg_type=0,
                    msg_seq=self._msg_seq,
                    content=msg.content,
                )
        except Exception:
            logger.exception("QQ send failed for %s", msg.chat_id)

    def _is_duplicate(self, msg_id: str) -> bool:
        if msg_id in self._seen_ids:
            return True
        self._seen_ids[msg_id] = None
        if len(self._seen_ids) > _DEDUP_CACHE_SIZE:
            self._seen_ids.popitem(last=False)
        return False

    async def handle_c2c(self, message: Any) -> None:
        """Called by the inner botpy client for C2C messages."""
        msg_id = getattr(message, "id", "")
        if self._is_duplicate(msg_id):
            return
        sender_id = getattr(message.author, "user_openid", "") or getattr(message.author, "id", "")
        chat_id = sender_id
        self._chat_type_cache[chat_id] = "c2c"
        content = getattr(message, "content", "").strip()
        if content:
            await self._handle_message(sender_id, chat_id, content, {"message_id": msg_id})

    async def handle_group_at(self, message: Any) -> None:
        """Called by the inner botpy client for group @mention messages."""
        msg_id = getattr(message, "id", "")
        if self._is_duplicate(msg_id):
            return
        sender_id = getattr(message.author, "member_openid", "") or getattr(message.author, "id", "")
        chat_id = getattr(message, "group_openid", "")
        self._chat_type_cache[chat_id] = "group"
        content = getattr(message, "content", "").strip()
        if content:
            await self._handle_message(sender_id, chat_id, content, {"message_id": msg_id, "group_openid": chat_id})


class _QQBotClient:
    """Wrapper around botpy.Client that forwards events to QQChannel."""

    def __init__(self, intents: Any, channel: QQChannel) -> None:
        import botpy
        self._inner = botpy.Client(intents=intents)
        self._channel = channel
        self.api = None

        client = self._inner

        @client.on_ready
        async def on_ready():
            logger.info("QQ bot connected")
            self.api = client.api

        @client.on_c2c_message_create
        async def on_c2c(message: Any):
            await channel.handle_c2c(message)

        @client.on_group_at_message_create
        async def on_group_at(message: Any):
            await channel.handle_group_at(message)

    async def start(self, appid: str, secret: str) -> None:
        await self._inner.start(appid=appid, secret=secret)

    async def close(self) -> None:
        await self._inner.close()
