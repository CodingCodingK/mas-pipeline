## ADDED Requirements

### Requirement: ChatSession ORM model
The system SHALL define a `ChatSession` SQLAlchemy ORM model in `src/models.py` mapping to the `chat_sessions` table.

Fields: `id` (int PK), `session_key` (str, unique), `channel` (str), `chat_id` (str), `project_id` (int), `conversation_id` (int), `metadata_` (JSONB), `status` (str, default "active"), `created_at` (datetime), `last_active_at` (datetime).

#### Scenario: ChatSession model fields
- **WHEN** ChatSession model is inspected
- **THEN** it SHALL have all specified fields with `session_key` having a unique constraint
