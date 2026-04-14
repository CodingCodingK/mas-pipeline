## MODIFIED Requirements

### Requirement: ChatSession mode field
The `chat_sessions` table SHALL have a `mode VARCHAR(20) NOT NULL DEFAULT 'chat'` column with allowed values `chat`, `autonomous`, and `bus_chat`. The `ChatSession` SQLAlchemy ORM model in `src/models.py` SHALL expose this column as `mode: Mapped[str]`.

#### Scenario: Default mode is chat
- **WHEN** a new `ChatSession` row is inserted without specifying `mode`
- **THEN** the row SHALL have `mode="chat"`

#### Scenario: Autonomous mode persisted
- **WHEN** a `ChatSession` is created with `mode="autonomous"`
- **THEN** the column SHALL persist the value and ORM read-back SHALL return `"autonomous"`

#### Scenario: bus_chat mode persisted
- **WHEN** a `ChatSession` is created with `mode="bus_chat"` by the third-party chat Gateway
- **THEN** the column SHALL persist the value and ORM read-back SHALL return `"bus_chat"`

#### Scenario: Existing rows backfilled
- **WHEN** the `mode` column is added to an existing `chat_sessions` table via migration
- **THEN** all existing rows SHALL receive `mode="chat"`

### Requirement: Session resolution accepts mode
`resolve_session(channel, chat_id, project_id, mode="chat")` in `src/bus/session.py` SHALL accept an optional `mode` parameter whose allowed values are `chat`, `autonomous`, and `bus_chat`. When creating a new session row (cache miss + PG miss), the `mode` SHALL be persisted on the new `ChatSession`. When loading an existing session, the stored `mode` SHALL be returned unchanged (the parameter is only used at creation time).

#### Scenario: New session uses requested mode
- **WHEN** `resolve_session("web", "abc", project_id=1, mode="autonomous")` is called and no session exists
- **THEN** the created `ChatSession` SHALL have `mode="autonomous"`

#### Scenario: New session uses bus_chat mode
- **WHEN** `resolve_session("discord", "channel-42", project_id=1, mode="bus_chat")` is called and no session exists
- **THEN** the created `ChatSession` SHALL have `mode="bus_chat"`

#### Scenario: Existing session ignores mode parameter
- **WHEN** a session with `mode="chat"` exists and `resolve_session(..., mode="autonomous")` is called for the same key
- **THEN** the returned session SHALL still have `mode="chat"` (mode is immutable after creation)
