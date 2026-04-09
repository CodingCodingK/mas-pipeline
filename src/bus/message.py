"""Protocol-agnostic message types for cross-platform communication."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    """Message received from an external platform."""

    channel: str        # "discord" / "qq" / "wechat"
    sender_id: str      # User identifier on the platform
    chat_id: str        # Conversation identifier on the platform
    content: str        # Message text
    metadata: dict = field(default_factory=dict)  # Platform-specific data

    @property
    def session_key(self) -> str:
        """Unique session identifier: channel:chat_id."""
        return f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send back to an external platform."""

    channel: str        # Target platform
    chat_id: str        # Target conversation
    content: str        # Response text
    reply_to: str | None = None  # Optional message ID for replies
    metadata: dict = field(default_factory=dict)  # Platform-specific directives
