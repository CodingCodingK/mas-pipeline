## ADDED Requirements

### Requirement: SessionRunner sets turn_id contextvar and emits agent_turn events
On entry to each turn (when `notify_new_message` triggers the runner's main loop to execute an agent turn), `SessionRunner` SHALL:

1. Generate a fresh UUID `turn_id`
2. Capture `started_at` timestamp
3. Capture `input_preview` — the `content[:preview_length]` of the most recent user message in `state.messages`
4. Set `current_turn_id.set(turn_id)` via the telemetry contextvar
5. Execute the agent_loop
6. On exit (normal `done`, exception, interrupt, or idle exit):
   - Capture `ended_at` timestamp and `output_preview` from the most recent assistant message
   - Emit one `agent_turn` event with all the above
   - Reset `current_turn_id` to its prior value via `current_turn_id.reset(token)`

`SessionRunner` SHALL NOT propagate contextvars manually; normal async task context inheritance (via `asyncio.create_task`) handles sub-agent linking.

#### Scenario: Normal turn emits complete agent_turn event
- **WHEN** a chat session runner completes one turn in response to a user message
- **THEN** one `agent_turn` event SHALL be emitted with a fresh `turn_id`, non-empty `input_preview` / `output_preview`, `stop_reason='done'`, and `duration_ms` matching wall-clock time

#### Scenario: Failed turn still emits event with error stop_reason
- **WHEN** a turn raises an unhandled exception mid-execution
- **THEN** the `agent_turn` event SHALL still be emitted with `stop_reason='error'` and whatever `output_preview` was captured (possibly empty)

#### Scenario: Concurrent turns on different sessions have independent contextvars
- **WHEN** two SessionRunners process turns concurrently on different sessions
- **THEN** each SHALL have its own `current_turn_id` in its task context
- **AND** tool_call events from each turn SHALL have the correct respective `parent_turn_id`

### Requirement: SessionRunner emits session_event for lifecycle transitions
`SessionRunner` SHALL emit a `session_event` at the following lifecycle transitions:
- `created` — when `SessionRunner.__init__` completes (new session) or `get_or_create_runner` creates a fresh runner
- `first_message` — when the first user message is appended to the session
- `idle_exit` — when the runner exits due to idle timeout
- `max_age_exit` — when the runner exits due to 24h max age
- `shutdown_exit` — when the runner exits due to FastAPI lifespan shutdown

Each event SHALL include `channel` (from `ChatSession.channel` if available), `mode` (`chat` or `autonomous`).

#### Scenario: New session emits created event
- **WHEN** `get_or_create_runner` creates a fresh `SessionRunner` for a new `chat_session_id`
- **THEN** one `session_event` with `session_event_type='created'` SHALL be emitted

#### Scenario: Idle exit emits idle_exit event
- **WHEN** a `SessionRunner` exits because idle timeout fired
- **THEN** one `session_event` with `session_event_type='idle_exit'` SHALL be emitted before the runner deregisters
