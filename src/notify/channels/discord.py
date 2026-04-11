"""Discord webhook channel (best-effort, logged-on-failure)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from src.notify.events import Notification

logger = logging.getLogger(__name__)


class DiscordChannel:
    name = "discord"

    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(
            timeout=timeout, limits=httpx.Limits(max_connections=20)
        )

    async def deliver(self, notification: Notification) -> None:
        body = {
            "content": f"**{notification.title}**\n{notification.body}",
            "username": "mas-pipeline",
        }
        host = urlparse(self._webhook_url).hostname or "?"
        try:
            response = await self._client.post(self._webhook_url, json=body)
            if response.status_code >= 400:
                logger.warning(
                    "discord: webhook %s returned HTTP %d for notification %s",
                    host, response.status_code, notification.notification_id,
                )
        except httpx.TimeoutException:
            logger.warning(
                "discord: webhook %s timed out for notification %s",
                host, notification.notification_id,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "discord: webhook %s failed (%s) for notification %s",
                host, exc, notification.notification_id,
            )
        except Exception:
            logger.exception(
                "discord: unexpected error delivering notification %s",
                notification.notification_id,
            )

    async def close(self) -> None:
        await self._client.aclose()
