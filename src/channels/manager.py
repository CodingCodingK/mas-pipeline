"""ChannelManager: lifecycle management and outbound dispatch for all platform adapters."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.bus.bus import MessageBus

from src.channels.base import BaseChannel

logger = logging.getLogger(__name__)

# Registry of channel name → class
_CHANNEL_REGISTRY: dict[str, type[BaseChannel]] = {}


def _register_channels() -> None:
    """Lazily register built-in channel classes."""
    if _CHANNEL_REGISTRY:
        return

    # Import here to avoid circular imports and optional dependency errors
    try:
        from src.channels.discord import DiscordChannel
        _CHANNEL_REGISTRY["discord"] = DiscordChannel
    except ImportError:
        logger.debug("Discord channel not available (missing websockets)")

    try:
        from src.channels.qq import QQChannel
        _CHANNEL_REGISTRY["qq"] = QQChannel
    except ImportError:
        logger.debug("QQ channel not available (missing qq-botpy)")

    try:
        from src.channels.wechat import WeChatChannel
        _CHANNEL_REGISTRY["wechat"] = WeChatChannel
    except ImportError:
        logger.debug("WeChat channel not available (missing dependencies)")


class ChannelManager:
    """Manages all platform channel adapters.

    Reads channel config, instantiates enabled channels, manages lifecycle,
    and dispatches outbound messages to the correct channel.
    """

    def __init__(self, channels_config: dict[str, Any], bus: MessageBus) -> None:
        self._bus = bus
        self._channels: dict[str, BaseChannel] = {}
        self._running = False

        _register_channels()

        for name, cls in _CHANNEL_REGISTRY.items():
            ch_config = channels_config.get(name, {})
            if not ch_config.get("enabled", False):
                continue
            self._channels[name] = cls(name=name, config=ch_config, bus=bus)
            logger.info("Channel '%s' registered", name)

    async def start_all(self) -> None:
        """Start all enabled channels concurrently."""
        if not self._channels:
            logger.warning("No channels enabled")
            return

        results = await asyncio.gather(
            *(ch.start() for ch in self._channels.values()),
            return_exceptions=True,
        )

        for (name, _), result in zip(self._channels.items(), results):
            if isinstance(result, Exception):
                logger.error("Channel '%s' failed to start: %s", name, result)
            else:
                logger.info("Channel '%s' started", name)

    async def stop_all(self) -> None:
        """Stop all channels, logging errors without raising."""
        self._running = False
        for name, ch in self._channels.items():
            try:
                await ch.stop()
                logger.info("Channel '%s' stopped", name)
            except Exception:
                logger.warning("Error stopping channel '%s'", name, exc_info=True)

    async def dispatch_outbound(self) -> None:
        """Continuously consume outbound queue and route to channels.

        Runs until self._running is set to False.
        """
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._bus.consume_outbound(), timeout=1.0
                )
            except TimeoutError:
                continue

            channel = self._channels.get(msg.channel)
            if channel is None:
                logger.warning(
                    "No channel '%s' for outbound message, skipping",
                    msg.channel,
                )
                continue

            try:
                await channel.send(msg)
            except Exception:
                logger.error(
                    "Failed to send outbound message via '%s'",
                    msg.channel, exc_info=True,
                )
