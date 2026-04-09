## ADDED Requirements

### Requirement: ChatSession model
The system SHALL define a `ChatSession` SQLAlchemy model mapping to the `chat_sessions` table with fields:

- `id: int` — primary key
- `session_key: str` — unique, format "channel:chat_id" (e.g., "discord:123456")
- `channel: str` — platform identifier
- `chat_id: str` — platform-side conversation ID
- `project_id: int` — FK to projects.id
- `conversation_id: int` — FK to conversations.id
- `metadata_: dict` — JSONB, platform-specific data
- `status: str` — "active" / "archived", default "active"
- `created_at: datetime`
- `last_active_at: datetime`

#### Scenario: ChatSession model fields
- **WHEN** ChatSession model is inspected
- **THEN** it SHALL have all specified fields with correct types and constraints

#### Scenario: session_key uniqueness
- **WHEN** two ChatSessions with the same session_key are inserted
- **THEN** the database SHALL raise a unique constraint violation

### Requirement: ChatSession CRUD with Redis cache
The system SHALL provide ChatSession management functions in `src/bus/session.py`:

- `resolve_session(session_key, channel, chat_id, project_id) -> ChatSession` — look up Redis first (`chat_session:{key}`), then PG; create if not exists (auto-creates Conversation); cache in Redis with TTL
- `refresh_session(session_key)` — update `last_active_at` in PG and refresh Redis TTL
- `get_session_history(conversation_id, max_messages) -> list[dict]` — load messages from Conversation via existing `get_messages()`, apply `clean_orphan_messages()`, trim to max_messages from the end

Redis cache key: `chat_session:{session_key}` storing JSON with `{session_id, project_id, conversation_id}`, TTL from `settings.channels.session_ttl_hours`.

#### Scenario: First message creates session
- **WHEN** `resolve_session("discord:123", "discord", "123", project_id=1)` is called and no session exists
- **THEN** a new ChatSession row SHALL be created in PG with a new Conversation, and the mapping SHALL be cached in Redis

#### Scenario: Cache hit avoids PG query
- **WHEN** `resolve_session` is called for a session_key that exists in Redis cache
- **THEN** the function SHALL return without querying PostgreSQL

#### Scenario: Cache miss falls back to PG
- **WHEN** Redis cache has expired but PG has the ChatSession
- **THEN** the function SHALL load from PG and re-cache in Redis

#### Scenario: History loading with orphan cleanup
- **WHEN** `get_session_history(conversation_id, max_messages=50)` is called
- **THEN** it SHALL return the last 50 messages with orphan tool_results removed

### Requirement: Gateway main loop
The system SHALL provide a Gateway class in `src/bus/gateway.py` that:

1. Continuously consumes from MessageBus.inbound
2. For each InboundMessage:
   a. Resolves ChatSession via `resolve_session(msg.session_key, ...)`
   b. Loads conversation history via `get_session_history()`
   c. Creates agent via `create_agent(role=configured_role, task_description=msg.content, ...)`
   d. Injects history into agent state messages
   e. Runs `run_agent_to_completion(state)`
   f. Extracts response from agent output
   g. Appends user message + assistant response to Conversation via `append_message()`
   h. Refreshes session activity timestamp
   i. Publishes OutboundMessage to MessageBus.outbound
3. Handles errors per-message: log and send error response, do not crash the loop
4. Supports per-session concurrency lock: messages within the same session_key are processed serially

#### Scenario: End-to-end message processing
- **WHEN** an InboundMessage arrives from Discord with content="hello"
- **THEN** Gateway SHALL resolve session, load history, run agent, save messages, and publish an OutboundMessage with the agent's response

#### Scenario: History injected into agent
- **WHEN** a session has 5 previous messages in Conversation
- **THEN** the agent SHALL receive those 5 messages as context before the current message

#### Scenario: Error in agent does not crash gateway
- **WHEN** agent_loop raises an exception for one message
- **THEN** Gateway SHALL log the error, send an error OutboundMessage, and continue processing next messages

#### Scenario: Same-session messages processed serially
- **WHEN** two messages arrive for the same session_key concurrently
- **THEN** Gateway SHALL process them one at a time in order

#### Scenario: Cross-session messages processed concurrently
- **WHEN** messages from different session_keys arrive
- **THEN** Gateway SHALL process them concurrently

### Requirement: Gateway CLI entry point
The system SHALL provide a gateway entry point that:

1. Initializes DB + Redis connections
2. Creates MessageBus
3. Creates ChannelManager with all enabled channels
4. Creates Gateway with configured project_id and role
5. Runs ChannelManager.start_all() + Gateway.run() + ChannelManager.dispatch_outbound() concurrently
6. On shutdown (SIGINT/SIGTERM): stops channels, then gateway

#### Scenario: Gateway startup
- **WHEN** the gateway entry point is invoked with valid config
- **THEN** all enabled channels SHALL be started and the gateway SHALL begin consuming messages

#### Scenario: Graceful shutdown
- **WHEN** SIGINT is received
- **THEN** all channels SHALL be stopped and DB/Redis connections SHALL be closed

### Requirement: Channels configuration in Settings
The system SHALL extend Settings with a `channels` configuration section:

- `project_id: int` — default project for all chat sessions (required)
- `role: str` — agent role to use (default: "assistant")
- `max_history: int` — max messages to load from history (default: 50)
- `session_ttl_hours: int` — Redis cache TTL (default: 24)
- `discord: dict` — Discord-specific config (enabled, token)
- `qq: dict` — QQ-specific config (enabled, app_id, secret)
- `wechat: dict` — WeChat-specific config (enabled, token, base_url)

#### Scenario: Default values
- **WHEN** Settings is loaded with an empty channels section
- **THEN** role SHALL default to "assistant", max_history to 50, session_ttl_hours to 24

#### Scenario: Channel-specific config access
- **WHEN** settings.channels contains discord.token="abc"
- **THEN** DiscordChannel SHALL receive "abc" as its token config
