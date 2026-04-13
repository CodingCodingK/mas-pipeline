## ADDED Requirements

### Requirement: SessionRunner tracks consecutive compact failures
`SessionRunner` SHALL maintain an integer field `consecutive_compact_failures: int = 0`. The field SHALL be incremented when a call to `auto_compact` or `reactive_compact` raises an exception and reset to `0` on successful compact. The field SHALL be module-local to the SessionRunner instance and NOT persisted to PG or Redis — it exists only for the lifetime of the runner.

#### Scenario: Counter starts at zero
- **WHEN** a new SessionRunner is constructed
- **THEN** `consecutive_compact_failures` SHALL equal `0`

#### Scenario: Counter increments on compact exception
- **WHEN** `auto_compact` raises an `LLMError` during the main loop
- **THEN** `consecutive_compact_failures` SHALL be incremented by 1

#### Scenario: Counter resets on compact success
- **WHEN** a subsequent `auto_compact` call returns successfully after prior failures
- **THEN** `consecutive_compact_failures` SHALL be reset to `0`

### Requirement: SessionRunner compact circuit breaker
When `consecutive_compact_failures >= 3`, `SessionRunner` SHALL skip all subsequent `auto_compact` and `reactive_compact` invocations for the remaining lifetime of the runner. The loop SHALL proceed without compact; if this causes a later LLM call to fail with a context-exceeded error, that error SHALL propagate through the normal error path and terminate the turn. The circuit-breaker trip event SHALL be logged at INFO level. No `StreamEvent(type="error")` SHALL be emitted solely because compact was skipped.

This behavior mirrors Claude Code's `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3` circuit breaker. The rationale for silent skipping: the user cannot take useful action on a "compact failed" notice except start a new session, and surfacing it as an error creates noise on every long conversation that hits transient rate-limit errors.

#### Scenario: Third consecutive failure trips breaker
- **WHEN** `consecutive_compact_failures` reaches `3`
- **THEN** subsequent calls to the compact code path within the main loop SHALL be skipped
- **AND** a single INFO log entry SHALL be written noting the trip

#### Scenario: Breaker stays tripped after reset
- **WHEN** the breaker has tripped and the main loop continues running
- **THEN** compact SHALL remain disabled even if the immediate cause clears
- **AND** the breaker SHALL only reset when the SessionRunner is destroyed and a new one is constructed

#### Scenario: No error StreamEvent emitted
- **WHEN** compact is skipped due to a tripped breaker
- **THEN** no `StreamEvent(type="error")` related to compact SHALL be emitted to subscribers

### Requirement: SessionRunner persists compact-produced messages
When `auto_compact` or `reactive_compact` returns a list containing new tail entries (the summary + boundary marker), `SessionRunner._persist_new_messages` SHALL treat those entries as normal new messages and append them to `conversations.messages` via the existing append-on-change path. No special-case logic SHALL be required — because compact is now append-only, `_pg_synced_count` SHALL continue to work as a simple monotonic counter.

#### Scenario: Compact output persists to PG
- **WHEN** `auto_compact` returns two new tail entries
- **THEN** the next `_persist_new_messages` call SHALL write both entries to `conversations.messages`
- **AND** `_pg_synced_count` SHALL be incremented by 2

#### Scenario: Counter does not drift after compact
- **WHEN** a session undergoes three compact cycles across many turns
- **THEN** `_pg_synced_count` SHALL exactly equal the total number of messages ever appended since construction
- **AND** no assistant reply SHALL be lost from PG
