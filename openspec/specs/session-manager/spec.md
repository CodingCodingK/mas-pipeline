## ADDED Requirements

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
