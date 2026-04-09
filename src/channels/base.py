"""BaseChannel: abstract interface for all platform adapters."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.bus.bus import MessageBus
    from src.bus.message import OutboundMessage

logger = logging.getLogger(__name__)


class BaseChannel(ABC):
    """Abstract base for platform channel adapters.

    All channels receive a MessageBus reference and push InboundMessages
    into it. The ChannelManager routes OutboundMessages back via send().
    """

    def __init__(self, name: str, config: dict[str, Any], bus: MessageBus) -> None:
        self._name = name
        self._config = config
        self._bus = bus

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    async def start(self) -> None:
        """Connect to the platform and begin listening for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect and clean up resources."""

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to the platform."""

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Construct InboundMessage and publish to bus.

        Called by platform-specific event handlers.
        """
        from src.bus.message import InboundMessage

        msg = InboundMessage(
            channel=self._name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            metadata=metadata or {},
        )
        await self._bus.publish_inbound(msg)
        logger.debug(
            "Channel '%s': message from %s in %s",
            self._name, sender_id, chat_id,
        )
