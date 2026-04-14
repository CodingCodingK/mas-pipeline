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

### Requirement: Non-HTTP subscribers are first-class consumers of the event stream
The SessionRunner subscriber interface (`add_subscriber()` / `remove_subscriber(queue)`) SHALL support non-HTTP consumers — including the bus gateway — on the same terms as SSE subscribers. A subscriber SHALL NOT need to be tied to an HTTP request lifecycle to attach.

Non-HTTP subscribers SHALL NOT be distinguished from SSE subscribers inside `SessionRunner`; the runner SHALL treat all subscriber queues uniformly for fan-out, slow-subscriber handling, and idle-exit counting.

#### Scenario: Bus gateway attaches as a subscriber
- **WHEN** `Gateway._process_message` calls `runner.add_subscriber()` outside of any HTTP request
- **THEN** the returned `asyncio.Queue[StreamEvent]` SHALL receive every event the runner fans out for the rest of the turn
- **AND** the runner SHALL include this subscriber when evaluating `len(self.subscribers) == 0` for idle-exit

#### Scenario: Bus subscriber counts toward keep-alive
- **WHEN** a SessionRunner has been idle 65 seconds but a bus gateway subscriber is still attached awaiting `done`
- **THEN** the runner SHALL NOT exit (len(subscribers) > 0)
- **AND** the runner SHALL continue serving fanned-out events to the bus subscriber

### Requirement: Non-HTTP subscribers MUST detach deterministically
Any non-HTTP subscriber SHALL detach via `remove_subscriber(queue)` no later than one of:
- receipt of a `StreamEvent` of type `"done"` on the queue, OR
- a consumer-chosen idle timeout (300 seconds for the bus gateway), OR
- an exception in the consumer's await loop (detach in a `finally` block).

Failure to detach SHALL cause the runner's subscriber set to leak; this requirement is the contract that prevents that leak.

#### Scenario: Bus subscriber detaches on done
- **WHEN** the bus gateway's subscriber queue receives a `done` StreamEvent
- **THEN** the bus gateway SHALL call `runner.remove_subscriber(queue)`
- **AND** the runner's `self.subscribers` set SHALL no longer contain that queue

#### Scenario: Bus subscriber detaches on timeout
- **WHEN** the bus gateway's subscriber queue has not received any event for 300 seconds
- **THEN** the bus gateway SHALL call `runner.remove_subscriber(queue)` in a finally block
- **AND** the runner's subscriber count SHALL decrement

#### Scenario: Bus subscriber detaches on exception
- **WHEN** the bus gateway's event-await loop raises an unexpected exception
- **THEN** the finally block SHALL call `runner.remove_subscriber(queue)`
- **AND** the subscriber queue SHALL NOT leak into `self.subscribers`

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

### Requirement: Per-turn memory recall overlay on the last user message
Before entering each `agent_loop` turn, `SessionRunner` SHALL call an internal helper `_overlay_recalled_memories()` that uses the existing `src/memory/selector.py` light-tier LLM selector to pick the most relevant project memories for the current user query and temporarily attach their full content to the last user message for the duration of one turn. The overlay SHALL NOT be persisted to PG.

The overlay mechanism SHALL use CONTENT MUTATION of the existing last user message (NOT list insertion of a new message), so that `state.messages` length remains unchanged and the `_pg_synced_count` position counter used by `_persist_new_messages` remains correct. The helper SHALL:

1. Short-circuit and return `None` when any of the following is true: there is no pending user turn, the runner has no `project_id`, the agent is not a chat agent with memory tools, or the project has zero memories.
2. Otherwise call `select_relevant(project_id, query=<last user message content>, limit=5)` to fetch at most 5 relevant full-content `Memory` objects. If the selector returns an empty list, return `None` without mutating state.
3. Format the selected memories as a `<recalled_memories>` XML block containing one `<memory>` child per entry (with `type`, `name`, `description`, full `content`).
4. Capture the original `content` of `state.messages[last_user_idx]`, then overwrite it with the `<recalled_memories>` block PREPENDED to the original content.
5. Return a `restore` callable (closure) that, when invoked, writes the original content back into `state.messages[last_user_idx]`.

The runner's main loop SHALL call this helper immediately before entering `agent_loop` and SHALL invoke the returned `restore` callable in a `finally` block so that the original user message is restored even if `agent_loop` raises. `_persist_new_messages` SHALL only run AFTER the finally block has executed, guaranteeing that PG never sees the overlaid content.

#### Scenario: Overlay prepends recalled memories to last user message
- **GIVEN** a chat SessionRunner for a project that has 3 memories
- **AND** the user has just sent "帮我生成一份期末试卷"
- **AND** `select_relevant` returns 2 memories (one `feedback` about question ratios, one `project` about the current textbook)
- **WHEN** the runner enters its next turn
- **THEN** `_overlay_recalled_memories` SHALL mutate the last user message's content to begin with a `<recalled_memories>` block containing both memories
- **AND** the original user query text SHALL appear after the block inside the same content field
- **AND** `state.messages` SHALL have the same length as before the call

#### Scenario: Restore runs after agent_loop completes normally
- **WHEN** the runner finishes a turn after an overlay was applied
- **THEN** the `finally` block SHALL invoke `restore()` before `_persist_new_messages` is called
- **AND** `state.messages[last_user_idx].content` SHALL equal the original unmodified user text
- **AND** the row appended to `Conversation.messages` SHALL NOT contain any `<recalled_memories>` substring

#### Scenario: Restore runs even when agent_loop raises
- **WHEN** `agent_loop` raises an exception mid-turn after an overlay was applied
- **THEN** the `finally` block SHALL still invoke `restore()`
- **AND** `state.messages[last_user_idx].content` SHALL be restored to the original user text before the exception propagates

#### Scenario: Empty project short-circuits without LLM call
- **GIVEN** the project has zero memories
- **WHEN** the runner enters a turn
- **THEN** `_overlay_recalled_memories` SHALL return `None` without calling `select_relevant`
- **AND** zero light-tier LLM calls SHALL be issued for memory selection
- **AND** the finally block's restore SHALL be a no-op

#### Scenario: Pipeline worker session skips overlay
- **GIVEN** a SessionRunner running an agent role without memory tools
- **WHEN** the runner enters a turn
- **THEN** `_overlay_recalled_memories` SHALL return `None` without calling the selector
- **AND** zero DB queries and zero LLM calls SHALL be issued for memory recall

#### Scenario: Selector returns empty result short-circuits overlay
- **GIVEN** the project has memories but `select_relevant` returns an empty list for the current query
- **WHEN** the runner enters a turn
- **THEN** `_overlay_recalled_memories` SHALL return `None`
- **AND** `state.messages[last_user_idx].content` SHALL remain unchanged

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

### Requirement: SessionRunner instantiates and owns an MCPManager
When `SessionRunner.start()` runs, it SHALL instantiate a fresh `MCPManager()` and `await manager.start(settings.mcp_servers)` before calling `create_agent`. The manager SHALL be stored on `self.mcp_manager` and passed as the `mcp_manager=` argument to `create_agent`. When `SessionRunner.stop()` runs (graceful exit, idle timeout, or error path in the `try/finally` block that guarantees registry cleanup), it SHALL `await self.mcp_manager.shutdown()` to terminate subprocess MCP servers.

#### Scenario: MCP manager constructed on start
- **WHEN** SessionRunner.start() is invoked
- **THEN** a new MCPManager SHALL be constructed and `.start(settings.mcp_servers)` SHALL be awaited before `create_agent`
- **AND** `create_agent` SHALL be called with `mcp_manager=self.mcp_manager`

#### Scenario: MCP manager shutdown on stop
- **WHEN** SessionRunner.stop() runs through its graceful exit path
- **THEN** `self.mcp_manager.shutdown()` SHALL be awaited before the runner returns control

#### Scenario: MCP startup failure is non-fatal
- **GIVEN** settings.mcp_servers contains a server whose subprocess fails to start
- **WHEN** SessionRunner.start() runs
- **THEN** SessionRunner SHALL still complete startup (MCPManager.start already logs-and-skips failures)
- **AND** the main agent loop SHALL begin normally with zero MCP tools from the failed server

#### Scenario: Both chat and autonomous modes get MCPManager
- **WHEN** SessionRunner is started for either `chat` or `autonomous` mode
- **THEN** the MCPManager lifecycle SHALL be identical in both modes (no mode-specific branching)

### Requirement: SessionRunner dispatches clawbot factory by role
`SessionRunner._build_agent_state` SHALL contain exactly one role-aware branch: when the resolved role equals `"clawbot"`, it SHALL call `src/clawbot/factory.py::create_clawbot_agent(...)` instead of the generic `create_agent(...)`. For every other role the existing generic `create_agent(...)` path SHALL be used unchanged.

This is the only clawbot-aware code outside of `src/clawbot/`. The generic `src/agent/factory.py`, `src/agent/context.py`, and `src/agent/loop.py` SHALL remain untouched.

#### Scenario: clawbot role dispatches to clawbot factory
- **WHEN** a SessionRunner is built with mode `bus_chat` (resolving to role `clawbot`)
- **THEN** `_build_agent_state` SHALL call `create_clawbot_agent(...)` and the returned state's first system message SHALL contain the SOUL bootstrap content

#### Scenario: Other roles dispatch to generic factory
- **WHEN** a SessionRunner is built with mode `chat` or `autonomous`
- **THEN** `_build_agent_state` SHALL call the generic `create_agent(...)` and SHALL NOT touch any clawbot module

### Requirement: SessionRunner accepts bus_chat mode
The `_MODE_TO_ROLE` mapping in `src/engine/session_runner.py` SHALL include the entry `"bus_chat": "clawbot"`. Constructing a `SessionRunner(mode="bus_chat", ...)` SHALL build an agent state for the `clawbot` role.

#### Scenario: bus_chat mode resolves to clawbot role
- **WHEN** `SessionRunner(session_id=1, mode="bus_chat", project_id=1)` is constructed and started
- **THEN** the agent state SHALL be built via `create_clawbot_agent(...)` with role `clawbot`

#### Scenario: Existing modes unchanged
- **WHEN** a SessionRunner is constructed with `mode="chat"` or `mode="autonomous"`
- **THEN** the role resolution SHALL continue to map to `assistant` or `coordinator` respectively, and no clawbot module SHALL be imported

