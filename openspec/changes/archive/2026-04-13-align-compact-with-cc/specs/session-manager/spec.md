## ADDED Requirements

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
