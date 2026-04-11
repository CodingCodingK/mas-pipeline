"""Enterprise WeChat webhook channel (best-effort, logged-on-failure)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from src.notify.events import Notification

logger = logging.getLogger(__name__)


class WechatChannel:
    name = "wechat"

    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.AsyncClient(
            timeout=timeout, limits=httpx.Limits(max_connections=20)
        )

    async def deliver(self, notification: Notification) -> None:
        body = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {notification.title}\n{notification.body}"
            },
        }
        host = urlparse(self._webhook_url).hostname or "?"
        try:
            response = await self._client.post(self._webhook_url, json=body)
            if response.status_code >= 400:
                logger.warning(
                    "wechat: webhook %s returned HTTP %d for notification %s",
                    host, response.status_code, notification.notification_id,
                )
        except httpx.TimeoutException:
            logger.warning(
                "wechat: webhook %s timed out for notification %s",
                host, notification.notification_id,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "wechat: webhook %s failed (%s) for notification %s",
                host, exc, notification.notification_id,
            )
        except Exception:
            logger.exception(
                "wechat: unexpected error delivering notification %s",
                notification.notification_id,
            )

    async def close(self) -> None:
        await self._client.aclose()
