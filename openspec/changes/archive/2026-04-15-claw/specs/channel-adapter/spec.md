## ADDED Requirements

### Requirement: BaseChannel abstract interface
The system SHALL define a BaseChannel ABC with the following interface:

- `name: str` property — channel identifier ("discord" / "qq" / "wechat")
- `async start()` — connect to platform, begin listening for messages
- `async stop()` — disconnect and clean up resources
- `async send(msg: OutboundMessage)` — send a message to the platform
- `async _handle_message(sender_id, chat_id, content, metadata=None)` — construct InboundMessage and publish to MessageBus.inbound

All channel adapters SHALL inherit from BaseChannel.

#### Scenario: _handle_message publishes to bus
- **WHEN** a channel calls `_handle_message(sender_id="u1", chat_id="c1", content="hello")`
- **THEN** an InboundMessage SHALL be published to the MessageBus inbound queue with the channel's name, sender_id, chat_id, and content

#### Scenario: start and stop lifecycle
- **WHEN** `start()` is called followed by `stop()`
- **THEN** the channel SHALL connect then cleanly disconnect without errors

### Requirement: ChannelManager manages all adapters
The system SHALL provide a ChannelManager that:

1. Reads `settings.channels` configuration
2. Instantiates only channels where `enabled: true`
3. `start_all()` — starts all enabled channels concurrently via asyncio.gather
4. `stop_all()` — stops all channels, logging errors without raising
5. `dispatch_outbound()` — continuously consumes MessageBus.outbound, routes each OutboundMessage to the matching channel's `send()` by `msg.channel`

#### Scenario: Only enabled channels are started
- **WHEN** config has discord.enabled=true and qq.enabled=false
- **THEN** ChannelManager SHALL start only the Discord channel

#### Scenario: Outbound routing to correct channel
- **WHEN** an OutboundMessage with channel="discord" is consumed from outbound queue
- **THEN** ChannelManager SHALL call `discord_channel.send(msg)`

#### Scenario: Unknown channel in outbound message
- **WHEN** an OutboundMessage with channel="unknown_platform" is consumed
- **THEN** ChannelManager SHALL log a warning and skip the message without raising

#### Scenario: Stop tolerates errors
- **WHEN** one channel raises during stop()
- **THEN** ChannelManager SHALL log the error and continue stopping remaining channels

### Requirement: Discord channel adapter
The system SHALL implement a DiscordChannel that:

- Connects to Discord Gateway via WebSocket
- Handles MESSAGE_CREATE events, extracting sender_id (author.id), chat_id (channel_id), content
- Sends messages via Discord REST API (POST /channels/{channel_id}/messages)
- Splits messages exceeding 2000 characters into multiple sends
- Handles WebSocket heartbeat and reconnection on disconnect
- Requires `token` in channel config

#### Scenario: Receive and forward text message
- **WHEN** a MESSAGE_CREATE event arrives from Discord with content="hello"
- **THEN** an InboundMessage SHALL be published with channel="discord", the author's ID, channel ID, and content

#### Scenario: Send text response
- **WHEN** `send(OutboundMessage(channel="discord", chat_id="ch1", content="hi"))` is called
- **THEN** a POST request SHALL be sent to Discord REST API for channel ch1

#### Scenario: Long message splitting
- **WHEN** send() is called with content longer than 2000 characters
- **THEN** the message SHALL be split into multiple sends, each under 2000 characters

### Requirement: QQ channel adapter
The system SHALL implement a QQChannel that:

- Uses qq-botpy SDK to connect via WebSocket
- Handles C2C (private) messages and group @mention messages
- Sends responses via the SDK's post_c2c_message / post_group_message APIs
- Deduplicates messages by message ID
- Requires `app_id` and `secret` in channel config

#### Scenario: Receive C2C message
- **WHEN** a C2C message event arrives from QQ
- **THEN** an InboundMessage SHALL be published with channel="qq", sender_id=user_openid, chat_id=user_openid

#### Scenario: Receive group @mention message
- **WHEN** a group_at_message event arrives from QQ
- **THEN** an InboundMessage SHALL be published with channel="qq", chat_id=group_openid

#### Scenario: Send response to correct target
- **WHEN** send() is called with a chat_id that maps to a group chat
- **THEN** the SDK's post_group_message SHALL be used

#### Scenario: Duplicate message ignored
- **WHEN** two events arrive with the same message ID
- **THEN** only the first SHALL be published to the bus

### Requirement: WeChat channel adapter
The system SHALL implement a WeChatChannel that:

- Connects to ilinkai API via HTTP long-poll (`ilink/bot/getupdates`)
- Parses message items (type 1 = text) from the poll response
- Sends text responses via `ilink/bot/sendmessage` with context_token
- Caches context_token per user (required for replies)
- Persists login token to local state file for session survival across restarts
- Requires `token` (or QR login flow) in channel config

#### Scenario: Receive text message via long-poll
- **WHEN** a poll response contains a message with item_type=1 (text)
- **THEN** an InboundMessage SHALL be published with channel="wechat", sender_id=from_user_id, content=text

#### Scenario: Send reply with context_token
- **WHEN** send() is called for a chat_id with a cached context_token
- **THEN** a POST to ilink/bot/sendmessage SHALL include the context_token

#### Scenario: Long message splitting
- **WHEN** send() is called with content longer than 4000 characters
- **THEN** the message SHALL be split into multiple sends

#### Scenario: Token persistence across restarts
- **WHEN** the channel starts with a previously saved token file
- **THEN** it SHALL use the saved token without requiring QR code login
