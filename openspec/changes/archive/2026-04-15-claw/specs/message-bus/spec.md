## ADDED Requirements

### Requirement: InboundMessage and OutboundMessage data types
The system SHALL define protocol-agnostic message types for cross-platform communication.

`InboundMessage` SHALL contain:
- `channel: str` — platform identifier ("discord" / "qq" / "wechat")
- `sender_id: str` — user identifier on the platform
- `chat_id: str` — conversation identifier on the platform
- `content: str` — message text
- `metadata: dict` — platform-specific data (guild_id, group_openid, etc.)
- `session_key` property — returns `f"{channel}:{chat_id}"`

`OutboundMessage` SHALL contain:
- `channel: str` — target platform
- `chat_id: str` — target conversation
- `content: str` — response text
- `reply_to: str | None` — optional message ID for replies
- `metadata: dict` — platform-specific directives

#### Scenario: InboundMessage session_key derivation
- **WHEN** an InboundMessage is created with channel="discord" and chat_id="123456"
- **THEN** `msg.session_key` SHALL return "discord:123456"

#### Scenario: OutboundMessage with metadata
- **WHEN** an OutboundMessage is created with metadata={"thread_ts": "123"}
- **THEN** the metadata SHALL be preserved and accessible by the channel adapter

### Requirement: MessageBus with inbound and outbound queues
The system SHALL provide a MessageBus class with two asyncio.Queue instances for decoupling platform adapters from agent processing.

- `publish_inbound(msg: InboundMessage)` — put message into inbound queue
- `consume_inbound() -> InboundMessage` — await and return next inbound message
- `publish_outbound(msg: OutboundMessage)` — put message into outbound queue
- `consume_outbound() -> OutboundMessage` — await and return next outbound message

#### Scenario: Inbound publish and consume
- **WHEN** `publish_inbound(msg)` is called followed by `consume_inbound()`
- **THEN** the same InboundMessage object SHALL be returned

#### Scenario: Outbound publish and consume
- **WHEN** `publish_outbound(msg)` is called followed by `consume_outbound()`
- **THEN** the same OutboundMessage object SHALL be returned

#### Scenario: Consume blocks until message available
- **WHEN** `consume_inbound()` is called on an empty queue
- **THEN** it SHALL block (await) until a message is published

#### Scenario: FIFO ordering
- **WHEN** three InboundMessages are published in order A, B, C
- **THEN** consuming three times SHALL return them in order A, B, C
