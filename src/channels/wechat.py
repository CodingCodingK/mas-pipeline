"""WeChat channel adapter: ilinkai HTTP long-poll API for personal WeChat."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.bus.message import OutboundMessage
from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
_POLL_TIMEOUT = 35
_MAX_MESSAGE_LEN = 4000
_ITEM_TEXT = 1

# Default state directory
_DEFAULT_STATE_DIR = Path.home() / ".mas-pipeline" / "wechat"


class WeChatChannel(BaseChannel):
    """Personal WeChat bot via ilinkai API (HTTP long-poll)."""

    def __init__(self, name: str, config: dict[str, Any], bus: Any) -> None:
        super().__init__(name, config, bus)
        self._base_url = config.get("base_url", _DEFAULT_BASE_URL)
        self._token = config.get("token", "")
        self._poll_timeout = config.get("poll_timeout", _POLL_TIMEOUT)
        self._state_dir = Path(config.get("state_dir", str(_DEFAULT_STATE_DIR)))
        self._running = False
        self._http: httpx.AsyncClient | None = None
        self._context_tokens: dict[str, str] = {}  # user_id -> context_token
        self._get_updates_buf: str = ""  # cursor for long-poll

        # Load saved state
        self._load_state()

    async def start(self) -> None:
        self._running = True
        self._http = httpx.AsyncClient(timeout=self._poll_timeout + 10)

        if not self._token:
            logger.error("WeChat: no token configured. Run login flow first.")
            return

        logger.info("WeChat channel starting (long-poll to %s)", self._base_url)

        while self._running:
            try:
                await self._poll_once()
            except httpx.ReadTimeout:
                pass  # Normal for long-poll
            except Exception:
                if not self._running:
                    break
                logger.exception("WeChat poll error. Retrying in 5s...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        if self._http:
            await self._http.aclose()
            self._http = None
        self._save_state()

    async def send(self, msg: OutboundMessage) -> None:
        if not self._http or not self._token:
            return

        context_token = self._context_tokens.get(msg.chat_id)
        if not context_token:
            logger.warning("WeChat: no context_token for %s, cannot reply", msg.chat_id)
            return

        chunks = _split_message(msg.content, _MAX_MESSAGE_LEN)
        for chunk in chunks:
            payload = {
                "to_user_id": msg.chat_id,
                "context_token": context_token,
                "item_list": [{"type": _ITEM_TEXT, "text_item": {"content": chunk}}],
            }
            try:
                resp = await self._http.post(
                    f"{self._base_url}/ilink/bot/sendmessage",
                    json=payload,
                    headers=self._auth_headers(),
                )
                if resp.status_code != 200:
                    logger.error("WeChat send failed (%d): %s", resp.status_code, resp.text)
            except Exception:
                logger.exception("WeChat send error for %s", msg.chat_id)

    # -- Long-poll internals --

    async def _poll_once(self) -> None:
        if not self._http:
            return

        payload: dict[str, Any] = {"timeout": self._poll_timeout}
        if self._get_updates_buf:
            payload["buf"] = self._get_updates_buf

        resp = await self._http.post(
            f"{self._base_url}/ilink/bot/getupdates",
            json=payload,
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            logger.warning("WeChat poll returned %d", resp.status_code)
            await asyncio.sleep(2)
            return

        data = resp.json()
        self._get_updates_buf = data.get("buf", self._get_updates_buf)

        for msg in data.get("msgs", []):
            await self._process_message(msg)

    async def _process_message(self, msg: dict) -> None:
        from_user_id = msg.get("from_user_id", "")
        context_token = msg.get("context_token", "")

        if context_token:
            self._context_tokens[from_user_id] = context_token

        item_list = msg.get("item_list", [])
        text_parts = []
        for item in item_list:
            if item.get("type") == _ITEM_TEXT:
                text_item = item.get("text_item", {})
                content = text_item.get("content", "")
                if content:
                    text_parts.append(content)

        content = "\n".join(text_parts).strip()
        if not content:
            return

        await self._handle_message(
            sender_id=from_user_id,
            chat_id=from_user_id,
            content=content,
            metadata={"message_id": msg.get("message_id", ""), "seq": msg.get("seq")},
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "AuthorizationType": "ilink_bot_token",
            "Content-Type": "application/json",
        }

    # -- State persistence --

    def _load_state(self) -> None:
        state_file = self._state_dir / "account.json"
        if not state_file.exists():
            return
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            self._token = self._token or data.get("token", "")
            self._get_updates_buf = data.get("get_updates_buf", "")
            self._context_tokens = data.get("context_tokens", {})
            if data.get("base_url"):
                self._base_url = data["base_url"]
            logger.info("WeChat: loaded state from %s", state_file)
        except Exception:
            logger.warning("WeChat: failed to load state", exc_info=True)

    def _save_state(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._state_dir / "account.json"
        data = {
            "token": self._token,
            "base_url": self._base_url,
            "get_updates_buf": self._get_updates_buf,
            "context_tokens": self._context_tokens,
        }
        try:
            state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.warning("WeChat: failed to save state", exc_info=True)


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
