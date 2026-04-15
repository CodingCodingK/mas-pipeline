"""Discord channel adapter: WebSocket Gateway + REST API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
import websockets

from src.bus.message import OutboundMessage
from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_DISCORD_API = "https://discord.com/api/v10"
_DISCORD_GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"

_OP_DISPATCH = 0
_OP_HEARTBEAT = 1
_OP_IDENTIFY = 2
_OP_HELLO = 10
_OP_HEARTBEAT_ACK = 11
_OP_RESUME = 6
_OP_RECONNECT = 7
_OP_INVALID_SESSION = 9

_MAX_MESSAGE_LEN = 2000


class DiscordChannel(BaseChannel):
    """Discord bot via WebSocket Gateway + REST API."""

    def __init__(self, name: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(name, config, bus)
        self._token = config["token"]
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._heartbeat_interval: float = 41.25
        self._sequence: int | None = None
        self._session_id: str | None = None
        self._bot_user_id: str | None = None
        self._running = False
        self._http: httpx.AsyncClient | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._resume_gateway_url: str | None = None

    async def start(self) -> None:
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        while self._running:
            try:
                url = self._resume_gateway_url or _DISCORD_GATEWAY
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    await self._gateway_loop(ws)
            except (websockets.ConnectionClosed, ConnectionError) as exc:
                if not self._running:
                    break
                logger.warning("Discord disconnected: %s. Reconnecting in 5s...", exc)
                await asyncio.sleep(5)
            except Exception:
                if not self._running:
                    break
                logger.exception("Discord error. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        if not self._http:
            return
        url = f"{_DISCORD_API}/channels/{msg.chat_id}/messages"
        auth_headers = {"Authorization": f"Bot {self._token}"}
        chunks = _split_message(msg.content, _MAX_MESSAGE_LEN)
        if not chunks:
            chunks = [""]
        for i, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"content": chunk}
            if i == 0 and msg.reply_to:
                payload["message_reference"] = {"message_id": msg.reply_to}

            # Attach files only on the LAST chunk so the attachment renders
            # next to the final bit of text, mirroring how humans send.
            last_chunk = i == len(chunks) - 1
            if last_chunk and msg.attachments:
                files = [
                    (
                        f"files[{idx}]",
                        (a.filename, a.content_bytes, a.mime),
                    )
                    for idx, a in enumerate(msg.attachments)
                ]
                data = {"payload_json": json.dumps(payload)}
                resp = await self._http.post(
                    url, headers=auth_headers, data=data, files=files
                )
            else:
                headers = {**auth_headers, "Content-Type": "application/json"}
                resp = await self._http.post(url, headers=headers, json=payload)

            if resp.status_code == 429:
                retry_after = resp.json().get("retry_after", 1)
                logger.warning("Discord rate limited, waiting %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                if last_chunk and msg.attachments:
                    resp = await self._http.post(
                        url, headers=auth_headers, data=data, files=files
                    )
                else:
                    resp = await self._http.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.error("Discord send failed (%d): %s", resp.status_code, resp.text)

    async def _gateway_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        async for raw in ws:
            data = json.loads(raw)
            op = data.get("op")
            t = data.get("t")
            if op == _OP_HELLO:
                self._heartbeat_interval = data["d"]["heartbeat_interval"] / 1000
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
                if self._session_id and self._sequence is not None:
                    await ws.send(json.dumps({
                        "op": _OP_RESUME,
                        "d": {"token": self._token, "session_id": self._session_id, "seq": self._sequence},
                    }))
                else:
                    await self._identify(ws)
            elif op == _OP_HEARTBEAT_ACK:
                pass
            elif op == _OP_RECONNECT:
                logger.info("Discord requested reconnect")
                await ws.close()
                return
            elif op == _OP_INVALID_SESSION:
                if not data.get("d", False):
                    self._session_id = None
                    self._sequence = None
                await asyncio.sleep(1)
                await ws.close()
                return
            elif op == _OP_DISPATCH:
                self._sequence = data.get("s")
                if t == "READY":
                    self._session_id = data["d"]["session_id"]
                    self._resume_gateway_url = data["d"].get("resume_gateway_url")
                    self._bot_user_id = data["d"]["user"]["id"]
                    logger.info("Discord connected as %s", data["d"]["user"]["username"])
                elif t == "MESSAGE_CREATE":
                    await self._on_message_create(data["d"])

    async def _identify(self, ws: websockets.WebSocketClientProtocol) -> None:
        await ws.send(json.dumps({
            "op": _OP_IDENTIFY,
            "d": {
                "token": self._token,
                "intents": 33281,
                "properties": {"os": "linux", "browser": "mas-pipeline", "device": "mas-pipeline"},
            },
        }))

    async def _heartbeat_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        try:
            while self._running:
                await asyncio.sleep(self._heartbeat_interval)
                await ws.send(json.dumps({"op": _OP_HEARTBEAT, "d": self._sequence}))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def _on_message_create(self, data: dict) -> None:
        author = data.get("author", {})
        if author.get("id") == self._bot_user_id or author.get("bot", False):
            return
        content = data.get("content", "").strip()
        if not content:
            return
        await self._handle_message(
            sender_id=author.get("id", ""),
            chat_id=data.get("channel_id", ""),
            content=content,
            metadata={"message_id": data.get("id"), "guild_id": data.get("guild_id")},
        )


def _split_message(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip("\n")
    return chunks
