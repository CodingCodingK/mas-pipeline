## Purpose
Defines `ChatSession` and `Conversation` persistence.
## Requirements
### Requirement: Conversation CRUD
The system SHALL provide Conversation management backed by PostgreSQL (`conversations` table, renamed from `user_sessions`) for persisting cross-run user conversation history at the project level.

- `create_conversation(project_id) -> Conversation` — creates a new row, returns ORM instance
- `get_conversation(conversation_id) -> Conversation` — retrieves by primary key, raises `ConversationNotFoundError` if missing
- `append_message(conversation_id, message: dict)` — JSON-appends to `messages` column, updates `updated_at`
- `get_messages(conversation_id) -> list[dict]` — returns the messages list from `messages` JSONB column

#### Scenario: Create and retrieve conversation
- **WHEN** `create_conversation(project_id=1)` is called
- **THEN** a new row is inserted with `messages=[]` and a `Conversation` object is returned with a valid `id`

#### Scenario: Append and read messages
- **WHEN** `append_message(conversation_id, {"role": "user", "content": "hello"})` is called twice, then `get_messages(conversation_id)` is called
- **THEN** the returned list SHALL contain both messages in insertion order

#### Scenario: Conversation not found
- **WHEN** `get_conversation(999)` is called with a non-existent id
- **THEN** it SHALL raise `ConversationNotFoundError`

### Requirement: Agent Session Redis hot storage
The system SHALL store Agent messages in Redis Lists for low-latency access during agent execution.

- `create_agent_session(agent_id, run_id) -> session_key` — generates key `agent_session:{agent_id}`, sets TTL
- `append_agent_message(session_key, message: dict)` — `RPUSH` JSON-serialized message
- `get_agent_messages(session_key) -> list[dict]` — `LRANGE 0 -1`, deserializes each element
- Session key format: `agent_session:{agent_id}`

#### Scenario: Create agent session with TTL
- **WHEN** `create_agent_session("agent-1", "run-1")` is called
- **THEN** a Redis key `agent_session:agent-1` SHALL be created with TTL equal to `settings.session.agent_ttl_hours` (default 24h)

#### Scenario: Append and retrieve agent messages
- **WHEN** three messages are appended via `append_agent_message` then `get_agent_messages` is called
- **THEN** all three messages SHALL be returned in order as `list[dict]`

#### Scenario: TTL expiry
- **WHEN** no messages are appended for longer than `agent_ttl_hours`
- **THEN** the Redis key SHALL be automatically expired and `get_agent_messages` SHALL return an empty list

### Requirement: Agent Session archival to PostgreSQL
The system SHALL archive Agent Session data from Redis to the `agent_sessions` PG table when the agent completes.

- `archive_agent_session(session_key, agent_role)` — reads all messages from Redis, inserts into PG `agent_sessions` table with `archived_at=now()`, deletes the Redis key

#### Scenario: Successful archive
- **WHEN** `archive_agent_session("agent_session:agent-1", "researcher")` is called and Redis contains 5 messages
- **THEN** a row SHALL be inserted into `agent_sessions` with `id=agent-1`, `agent_role="researcher"`, `messages` containing the 5 messages, and `archived_at` set
- **AND** the Redis key SHALL be deleted

#### Scenario: Archive empty session
- **WHEN** `archive_agent_session` is called but the Redis key has expired or is empty
- **THEN** a row SHALL still be inserted with `messages=[]` and the function SHALL NOT raise an error

### Requirement: Orphan tool_result cleanup on load
When loading messages (from either Conversation or Agent Session), the system SHALL scan for orphan `tool` role messages whose `tool_call_id` has no matching `tool_calls` entry in any preceding `assistant` message, and discard them.

#### Scenario: Clean messages pass through unchanged
- **WHEN** messages contain matching assistant tool_calls and tool results
- **THEN** `clean_orphan_messages(messages)` returns the same messages

#### Scenario: Orphan tool result removed
- **WHEN** messages contain a `{"role": "tool", "tool_call_id": "tc_999"}` but no assistant message has a tool_call with id `tc_999`
- **THEN** that message SHALL be removed from the returned list

### Requirement: ORM models for sessions
The system SHALL define `Conversation` and `AgentSessionRecord` SQLAlchemy ORM models in `src/models.py` mapping to the `conversations` and `agent_sessions` tables respectively.

#### Scenario: Conversation model fields
- **WHEN** Conversation model is inspected
- **THEN** it SHALL have fields: `id` (int PK), `project_id` (int FK), `messages` (JSON), `created_at`, `updated_at`

#### Scenario: AgentSessionRecord model fields
- **WHEN** AgentSessionRecord model is inspected
- **THEN** it SHALL have fields: `id` (str PK), `run_id` (int FK nullable), `agent_role` (str), `messages` (JSON), `summary` (str nullable), `token_count` (int nullable), `created_at`, `archived_at`

### Requirement: DB table rename user_sessions to conversations
The `user_sessions` table in `scripts/init_db.sql` SHALL be renamed to `conversations`. The `workflow_runs.session_id` FK reference SHALL be updated to reference `conversations(id)`. Index name SHALL be updated to `idx_conversations_project`.

#### Scenario: Table name in init_db.sql
- **WHEN** `scripts/init_db.sql` is inspected
- **THEN** the table SHALL be named `conversations` with the same columns as the original `user_sessions`

#### Scenario: FK reference updated
- **WHEN** `workflow_runs` table definition is inspected
- **THEN** `session_id` SHALL reference `conversations(id)`

### Requirement: ChatSession mode field
The `chat_sessions` table SHALL have a `mode VARCHAR(20) NOT NULL DEFAULT 'chat'` column with allowed values `chat` and `autonomous`. The `ChatSession` SQLAlchemy ORM model in `src/models.py` SHALL expose this column as `mode: Mapped[str]`.

#### Scenario: Default mode is chat
- **WHEN** a new `ChatSession` row is inserted without specifying `mode`
- **THEN** the row SHALL have `mode="chat"`

#### Scenario: Autonomous mode persisted
- **WHEN** a `ChatSession` is created with `mode="autonomous"`
- **THEN** the column SHALL persist the value and ORM read-back SHALL return `"autonomous"`

#### Scenario: Existing rows backfilled
- **WHEN** the `mode` column is added to an existing `chat_sessions` table via migration
- **THEN** all existing rows SHALL receive `mode="chat"`

### Requirement: Session resolution accepts mode
`resolve_session(channel, chat_id, project_id, mode="chat")` in `src/bus/session.py` SHALL accept an optional `mode` parameter. When creating a new session row (cache miss + PG miss), the `mode` SHALL be persisted on the new `ChatSession`. When loading an existing session, the stored `mode` SHALL be returned unchanged (the parameter is only used at creation time).

#### Scenario: New session uses requested mode
- **WHEN** `resolve_session("web", "abc", project_id=1, mode="autonomous")` is called and no session exists
- **THEN** the created `ChatSession` SHALL have `mode="autonomous"`

#### Scenario: Existing session ignores mode parameter
- **WHEN** a session with `mode="chat"` exists and `resolve_session(..., mode="autonomous")` is called for the same key
- **THEN** the returned session SHALL still have `mode="chat"` (mode is immutable after creation)

### Requirement: get_session_history loads full conversation
`get_session_history(conversation_id) -> list[dict]` in `src/bus/session.py` SHALL load the complete `messages` JSONB array from the `conversations` row and return it without truncation. The function SHALL NOT accept a `max_messages` / `limit` parameter.

This behavior matches Claude Code's `loadFullLog` semantics on session resume. Upstream callers (primarily `SessionRunner._load_history_from_pg`) rely on getting the full history so that compact has enough material to work with; truncating at load time would make compact unable to reach early turns.

The function SHALL still apply `clean_orphan_messages` before returning, preserving the existing orphan-tool-result cleanup contract.

#### Scenario: Short conversation loaded in full
- **WHEN** a conversation has 42 messages and `get_session_history(conversation_id)` is called
- **THEN** all 42 messages SHALL be returned in insertion order

#### Scenario: Long conversation loaded in full
- **WHEN** a conversation has 1500 messages and `get_session_history(conversation_id)` is called
- **THEN** all 1500 messages SHALL be returned
- **AND** the function SHALL NOT apply a length cap

#### Scenario: Parameter removed
- **WHEN** calling code attempts `get_session_history(conversation_id, max_messages=200)`
- **THEN** the call SHALL fail with a `TypeError` — the parameter no longer exists

