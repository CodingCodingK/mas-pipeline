# session-runner Specification

## Purpose
TBD - created by archiving change add-rest-api-session-runner. Update Purpose after archive.
## Requirements
### Requirement: SessionRunner is a per-session long-running asyncio task
The system SHALL define `SessionRunner` in `src/engine/session_runner.py` as a class wrapping a single asyncio Task that runs the `agent_loop` for one chat session. Each instance SHALL hold:
- `session_id: int` — the `chat_sessions.id`
- `mode: str` — `chat` or `autonomous`
- `state: AgentState` — created from the appropriate role file (`assistant.md` for chat, `coordinator.md` for autonomous)
- `wakeup: asyncio.Event` — set whenever a new message lands in the conversation
- `subscribers: set[asyncio.Queue]` — SSE subscriber event queues
- `child_tasks: set[asyncio.Task]` — references to spawned sub-agent background tasks
- `last_active_at: datetime` — updated on every message arrival or event push

#### Scenario: SessionRunner construction
- **WHEN** `SessionRunner(session_id=1, mode="chat", project_id=1)` is created and started
- **THEN** the AgentState SHALL be built via `create_agent("assistant", ..., project_id=1)`
- **AND** the underlying asyncio task SHALL be running

#### Scenario: Autonomous mode loads coordinator role
- **WHEN** a SessionRunner with `mode="autonomous"` is constructed
- **THEN** the AgentState SHALL be built via `create_agent("coordinator", ...)`

### Requirement: SessionRunner main loop awaits the wakeup event
The SessionRunner main loop SHALL run as an async generator over `agent_loop(state)`, pushing each `StreamEvent` to all subscribers. After agent_loop exits, the runner SHALL evaluate continuation:

1. If `running_agent_count == 0` AND no unread messages in `state.messages` → wait on `self.wakeup.wait()` until a new message arrives or idle timeout fires
2. Otherwise → re-enter `agent_loop(state)` immediately

The runner SHALL NOT busy-poll; the only suspension primitive SHALL be `await self.wakeup.wait()` (or `asyncio.wait_for` when applying idle timeout).

#### Scenario: Wait for next user message
- **WHEN** agent_loop completes a turn, no sub-agents are running, no new messages arrived
- **THEN** the SessionRunner SHALL await `self.wakeup` with zero CPU usage
- **AND** zero LLM calls and zero DB queries SHALL occur during the wait

#### Scenario: Wake on user message
- **WHEN** the runner is waiting on `self.wakeup` and a new user message is appended via `POST /api/sessions/{id}/messages`
- **THEN** `self.wakeup.set()` SHALL be called
- **AND** the runner SHALL resume and re-enter `agent_loop`

#### Scenario: Wake on sub-agent completion
- **WHEN** the runner is waiting on `self.wakeup` and a spawned sub-agent completes (writing a `<task-notification>` user message into the conversation)
- **THEN** `self.wakeup.set()` SHALL be called
- **AND** the runner SHALL resume and re-enter `agent_loop`

### Requirement: SessionRunner pushes events to subscribers
For every `StreamEvent` yielded by `agent_loop`, SessionRunner SHALL enqueue the event into every subscriber queue in `self.subscribers`. Each subscriber queue SHALL have a bounded size (default 100). When a subscriber queue is full, the runner SHALL drop the oldest event for that subscriber and log a WARNING; it SHALL NOT block the main loop.

#### Scenario: Event fan-out
- **WHEN** SessionRunner has 3 active subscribers and `agent_loop` yields a `MessageDelta` event
- **THEN** the event SHALL be enqueued in all 3 subscriber queues

#### Scenario: Slow subscriber does not block runner
- **WHEN** one subscriber queue is full (100 events)
- **THEN** the runner SHALL drop the oldest event from that subscriber queue, enqueue the new event, log a WARNING, and continue serving other subscribers without delay

### Requirement: Persisted user-role messages on exit of each turn
After `agent_loop` produces an assistant message or before re-entering on a wakeup, SessionRunner SHALL append any new in-memory `state.messages` entries to the corresponding `Conversation.messages` JSONB column via `append_message()`. The runner SHALL NOT hold a PG transaction across `await self.wakeup.wait()`.

#### Scenario: Assistant message persisted
- **WHEN** agent_loop yields a `MessageEnd` event with role=assistant
- **THEN** the assistant message SHALL be appended to `Conversation.messages` before the next turn begins

#### Scenario: No transaction held during wait
- **WHEN** SessionRunner is awaiting `self.wakeup`
- **THEN** no PG connection SHALL be checked out from the pool

### Requirement: Idle timeout and max age cause graceful exit
SessionRunner SHALL exit when ALL of the following are true:
- `len(self.subscribers) == 0`
- `state.running_agent_count == 0`
- `now() - last_active_at >= settings.session.idle_timeout_seconds` (default 60)

OR when:
- `now() - created_at >= settings.session.max_age_seconds` (default 86400 = 24 hours)

On exit, the runner SHALL: cancel all `child_tasks`, deregister itself from the global registry, release `state` references, and complete its asyncio task.

#### Scenario: Idle exit
- **WHEN** SessionRunner has been idle (no subscribers, no running agents, no new messages) for ≥ 60 seconds
- **THEN** the runner SHALL exit cleanly and remove itself from the registry

#### Scenario: Active subscribers prevent exit
- **WHEN** SessionRunner has been idle for 60 seconds but has 1 active SSE subscriber
- **THEN** the runner SHALL NOT exit

#### Scenario: Running sub-agent prevents exit
- **WHEN** SessionRunner has 0 subscribers, idle 60 seconds, but `state.running_agent_count > 0`
- **THEN** the runner SHALL NOT exit

#### Scenario: 24-hour hard cap
- **WHEN** a SessionRunner has been alive for 24 hours regardless of activity
- **THEN** the runner SHALL exit and clean up

### Requirement: Try/finally guarantees registry cleanup
The SessionRunner main coroutine SHALL be wrapped in `try/finally`. The `finally` block SHALL unconditionally remove the runner from the global `_session_runners` dict and cancel all `child_tasks`, even if the main loop raised an unhandled exception.

#### Scenario: Exception during agent_loop
- **WHEN** the SessionRunner's agent_loop raises an unhandled exception
- **THEN** the finally block SHALL remove the runner from `_session_runners`
- **AND** all `child_tasks` SHALL be cancelled
- **AND** the exception SHALL be logged at ERROR level

### Requirement: Global SessionRunner registry
The system SHALL define `src/engine/session_registry.py` containing:
- `_session_runners: dict[int, SessionRunner]` — keyed by `chat_sessions.id`
- `_registry_lock: asyncio.Lock` — serializes create/destroy
- `get_or_create_runner(session_id, mode, project_id) -> SessionRunner` — idempotent factory
- `get_runner(session_id) -> SessionRunner | None` — lookup
- `shutdown_all() -> None` — graceful shutdown for FastAPI lifespan

`get_or_create_runner` SHALL hold `_registry_lock` only during dict mutation, not across SessionRunner construction's awaits.

#### Scenario: Idempotent create
- **WHEN** `get_or_create_runner(1, "chat", 1)` is called twice concurrently
- **THEN** exactly one SessionRunner SHALL be created
- **AND** both callers SHALL receive the same instance

#### Scenario: Lookup miss
- **WHEN** `get_runner(999)` is called and no such session is active
- **THEN** the function SHALL return None

### Requirement: Idle GC background task
On FastAPI startup, the system SHALL launch a background asyncio task that runs every 60 seconds and inspects all entries in `_session_runners`. For each entry whose runner has exceeded its idle timeout or 24-hour age cap, the GC task SHALL trigger graceful exit.

#### Scenario: GC sweeps idle runners
- **WHEN** the GC task runs and finds a SessionRunner that has been idle 90 seconds with no subscribers and no running agents
- **THEN** the GC task SHALL request the runner to exit

#### Scenario: GC tolerates registry mutation
- **WHEN** the GC task is iterating and a new SessionRunner is created concurrently
- **THEN** the GC SHALL complete its current sweep without crashing (snapshot iteration)

### Requirement: Graceful shutdown on FastAPI lifespan exit
On FastAPI shutdown, the lifespan handler SHALL call `shutdown_all()` which iterates all SessionRunners, sets their `wakeup` event, and waits up to 5 seconds for each underlying task to finish. Any task still alive after the timeout SHALL be cancelled.

#### Scenario: Clean shutdown
- **WHEN** the FastAPI app shuts down with 3 active SessionRunners
- **THEN** `shutdown_all()` SHALL be called
- **AND** all 3 runners SHALL exit (cleanly or via cancellation) before the process exits

### Requirement: PG LISTEN/NOTIFY hook for cross-process wakeup
The system SHALL register a single background task per process that issues `LISTEN session_wakeup` on a dedicated PG connection. When a `NOTIFY session_wakeup, '<session_id>'` arrives, the task SHALL look up the SessionRunner for that id in the local registry and call `runner.wakeup.set()` if present.

This task SHALL exist for forward compatibility with multi-process deployment but SHALL NOT be the primary wakeup path in single-process mode.

#### Scenario: Same-process NOTIFY ignored if runner is local
- **WHEN** a NOTIFY arrives for session 1 and `_session_runners[1]` exists in the same process
- **THEN** the listener SHALL call `runner.wakeup.set()` (idempotent — already set by the in-process path)

#### Scenario: Cross-process NOTIFY without local runner is no-op
- **WHEN** a NOTIFY arrives for session 1 and no SessionRunner for session 1 exists in the local registry
- **THEN** the listener SHALL ignore it without error

