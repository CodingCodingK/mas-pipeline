"""MessageBus: two asyncio.Queue instances decoupling platform adapters from agent processing."""

from __future__ import annotations

import asyncio

from src.bus.message import InboundMessage, OutboundMessage


class MessageBus:
    """Inbound + outbound message queues for platform ↔ system boundary."""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Channel adapters push user messages here."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Gateway pulls messages from here."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Gateway pushes responses here."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """ChannelManager pulls messages to send back to platforms."""
        return await self.outbound.get()
