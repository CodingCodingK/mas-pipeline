# clawbot-run-lifecycle Specification

## Purpose
TBD - created by archiving change add-clawbot-third-party-chat. Update Purpose after archive.
## Requirements
### Requirement: PendingRun in-memory store with TTL
The system SHALL store pending runs in a process-local dict keyed by session_key, with each entry expiring after 90 seconds via `asyncio.get_event_loop().call_later`. Restart loss is acceptable; the store MUST NOT be persisted to Redis or PostgreSQL.

#### Scenario: TTL expiry
- **WHEN** a `PendingRun` has been in the store for 90 seconds without confirmation
- **THEN** the cleanup callback removes it silently (no broadcast to the channel)

#### Scenario: Per-session isolation
- **WHEN** two different `chat_id`s each have a pending run
- **THEN** the entries are isolated by session_key and confirming one does not affect the other

#### Scenario: Restart loss
- **WHEN** the process restarts while a pending slot exists
- **THEN** the slot is gone and a subsequent user "y" causes the LLM to reply "the previous request expired" based on conversation history

### Requirement: LLM-driven intent recognition for pending runs
The system SHALL inject the active `PendingRun` summary into the runtime-context block when a slot exists, instructing the LLM to call `confirm_pending_run` / `cancel_pending_run` / new `start_project_run` based on user intent. The system MUST NOT use a regex or keyword whitelist to detect "y/n" confirmations.

#### Scenario: Pending injected into context
- **WHEN** clawbot starts a turn and the session has a pending slot
- **THEN** the runtime-context block includes the pending project_id, pipeline, and inputs summary plus an instruction line on the three available actions

#### Scenario: Group consensus
- **WHEN** user A creates a pending run and user B in the same chat replies "ok go"
- **THEN** the LLM may call `confirm_pending_run` and the run starts (per-chat_id session, group consensus is intentional)

### Requirement: ChatProgressReporter subscribes to pipeline EventBus
The system SHALL provide `src/clawbot/progress_reporter.py::ChatProgressReporter` which subscribes to a pipeline run's `EventBus` and emits exactly three message types to the channel: `run_start`, `interrupt`, and `done` (with sub-status `completed` or `failed`). Intermediate node transitions MUST NOT be pushed.

#### Scenario: Three-event granularity
- **WHEN** a pipeline run transitions through start → node A → node B → interrupt → resume → done
- **THEN** the reporter publishes exactly three outbound messages: run_start, interrupt, done

#### Scenario: Run id prefix
- **WHEN** any progress message is published
- **THEN** its body begins with `[run #<run_id>]` so parallel runs in the same chat are distinguishable

### Requirement: Double-write progress to outbound and conversation
The system SHALL have the reporter both call `bus.publish_outbound(...)` (push to channel) and `append_message(conversation_id, role="system", metadata={"source": "progress_reporter"}, ...)` (write to conversation history) for every progress event.

#### Scenario: History visibility
- **WHEN** the reporter emits a `done` event
- **THEN** the conversation row in PostgreSQL contains a system message recording the event so a later clawbot turn can reference it

#### Scenario: SessionRunner pickup
- **WHEN** the SessionRunner's next turn runs `_sync_inbound_from_pg()`
- **THEN** any progress messages appended since the last sync are pulled into `state.messages`

### Requirement: Gateway-level reporter registry
The system SHALL maintain a `dict[run_id, ReporterTask]` on the Gateway instance (not on SessionRunner). Reporters MUST outlive the SessionRunner so that a run continuing after a session idle-timeout still pushes progress.

#### Scenario: Reporter outlives session
- **WHEN** a SessionRunner exits due to idle timeout while a pipeline run is still executing
- **THEN** the Gateway's reporter task continues to publish progress and write to conversation

#### Scenario: Cleanup on done
- **WHEN** a reporter publishes the `done` event
- **THEN** it removes its entry from the Gateway registry

#### Scenario: Restart degradation
- **WHEN** the process restarts mid-run
- **THEN** the registry is empty and users may call `get_run_progress(run_id)` to manually query state

### Requirement: Three-layer physical isolation between clawbot and pipeline
The system SHALL ensure pipeline runs spawned by `confirm_pending_run` execute in a separate `asyncio.Task` with their own `create_agent(role=node.role, history=[])` calls per node. The clawbot session's `state.messages` list MUST NOT be shared with any pipeline node agent.

#### Scenario: Independent message lists
- **WHEN** a clawbot session and its launched pipeline run execute concurrently
- **THEN** `state.messages` for the clawbot agent and any node agent are distinct Python list objects with no aliasing

#### Scenario: Pipeline node history is empty
- **WHEN** a pipeline node agent is created
- **THEN** its starting history is `[]` (per `factory.py` line 148) regardless of clawbot's conversation length

