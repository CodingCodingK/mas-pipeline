# Telemetry Collection

## Purpose
Capture structured runtime observability events (LLM calls, tool calls, agent turns, spawns, pipeline transitions, session lifecycle, hooks, errors) into a single append-only store that supports run/session/project rollups, cost accounting, and parent-child tree reconstruction via contextvars.
## Requirements
### Requirement: Telemetry event storage schema
The system SHALL persist telemetry events in a single PG table `telemetry_events` with the following columns:
- `id BIGSERIAL PRIMARY KEY`
- `ts TIMESTAMPTZ NOT NULL DEFAULT now()`
- `event_type TEXT NOT NULL` — one of `llm_call`, `tool_call`, `agent_turn`, `agent_spawn`, `pipeline_event`, `session_event`, `hook_event`, `error`
- `project_id INT NOT NULL` — FK to `projects.id`
- `run_id TEXT NULL` — pipeline run id; nullable for chat/autonomous events
- `session_id INT NULL` — chat session id; nullable for pipeline events
- `agent_role TEXT NULL` — active agent role at emit time, if known
- `payload JSONB NOT NULL` — event-type-specific fields

Indexes:
- `idx_telemetry_run_ts` on `(run_id, ts)` WHERE `run_id IS NOT NULL`
- `idx_telemetry_session_ts` on `(session_id, ts)` WHERE `session_id IS NOT NULL`
- `idx_telemetry_event_ts` on `(event_type, ts)`
- `idx_telemetry_project_ts` on `(project_id, ts)`
- `idx_telemetry_payload_gin` GIN on `payload`

The table SHALL be append-only — no `UPDATE` or `DELETE` issued by collector or query code. (Retention cleanup by operational scripts is out of scope.)

#### Scenario: Event is persisted with all required fields
- **WHEN** `TelemetryCollector.record_llm_call(...)` is called and the batched writer flushes
- **THEN** a row SHALL appear in `telemetry_events` with `event_type='llm_call'`, non-null `ts` / `project_id` / `payload`, and one of `run_id` / `session_id` populated based on context

#### Scenario: Polymorphic payload per event type
- **WHEN** events of different types land in the same flush batch
- **THEN** each row SHALL have the event-type-specific JSONB structure under `payload` and all rows SHALL share the common columns

#### Scenario: Query performance on run lookup
- **WHEN** a query `SELECT * FROM telemetry_events WHERE run_id = ? ORDER BY ts` is issued with the index present
- **THEN** PG SHALL use `idx_telemetry_run_ts`

### Requirement: Eight event types cover all observability needs
The telemetry collector SHALL emit the following event types, each with a fixed payload schema. Additional fields beyond those listed are allowed per event but MUST NOT remove listed fields.

**`llm_call`** payload fields:
- `provider: str`, `model: str`
- `input_tokens: int`, `output_tokens: int`, `cache_read_tokens: int`, `cache_creation_tokens: int`
- `latency_ms: int`
- `finish_reason: str`
- `cost_usd: float | null` (null when pricing table lacks the model)
- `turn_id: str` (UUID from contextvar), `parent_turn_id: str` (same as `turn_id`; present for query uniformity)

**`tool_call`** payload fields:
- `tool_name: str`
- `args_preview: str` (truncated per `preview_length`)
- `duration_ms: int`
- `success: bool`
- `error_type: str | null`, `error_msg: str | null`
- `parent_turn_id: str`

**`agent_turn`** payload fields:
- `turn_id: str` (UUID)
- `agent_role: str`
- `turn_index: int` (per-session monotonic counter)
- `started_at: str` (ISO), `ended_at: str` (ISO)
- `duration_ms: int`
- `message_count_delta: int`
- `stop_reason: str` (one of `done`, `interrupt`, `error`, `idle_exit`)
- `input_preview: str`, `output_preview: str` (both truncated per `preview_length`)
- `spawned_by_spawn_id: str | null` (set if this turn is on a spawned child)

**`agent_spawn`** payload fields:
- `spawn_id: str` (UUID generated when this event is emitted)
- `parent_role: str`, `child_role: str`
- `task_preview: str` (truncated per `preview_length`)
- `parent_turn_id: str`

**`pipeline_event`** payload fields:
- `pipeline_event_type: str` (one of `pipeline_start`, `node_start`, `node_end`, `node_failed`, `paused`, `resumed`, `pipeline_end`)
- `pipeline_name: str`
- `node_name: str | null`
- `duration_ms: int | null`
- `error_msg: str | null`

**`session_event`** payload fields:
- `session_event_type: str` (one of `created`, `first_message`, `idle_exit`, `max_age_exit`, `shutdown_exit`)
- `channel: str | null`
- `mode: str` (`chat` or `autonomous`)

**`hook_event`** payload fields:
- `hook_type: str` (e.g., `PreToolUse`, `PostToolUse`)
- `decision: str` (`allow`, `deny`, `ask`)
- `latency_ms: int`
- `rule_matched: str | null`
- `parent_turn_id: str | null`

**`error`** payload fields:
- `source: str` (one of `llm`, `tool`, `pipeline`, `gateway`, `session`, `hook`)
- `error_type: str`
- `message: str` (truncated to 500 chars)
- `stacktrace_hash: str` (SHA256 of stacktrace for dedup)
- `context: dict` (free-form, event-source-specific)
- `parent_turn_id: str | null`

#### Scenario: llm_call captures token breakdown
- **WHEN** an LLM invocation completes with `LLMResponse.usage = {input_tokens: 1000, output_tokens: 500, cache_read_tokens: 800, cache_creation_tokens: 200}`
- **THEN** a `llm_call` event SHALL be emitted with all four token fields copied verbatim

#### Scenario: tool_call linked to its parent turn
- **WHEN** a tool is invoked inside an agent_turn with `turn_id='abc-123'`
- **THEN** the emitted `tool_call` event SHALL have `payload.parent_turn_id='abc-123'` populated from the contextvar

#### Scenario: agent_turn captures previews at configured length
- **WHEN** the runner enters a turn with input message `"Please research ..."` 500 chars long and `preview_length=30`
- **THEN** the `agent_turn.payload.input_preview` SHALL be exactly the first 30 chars of that message

#### Scenario: agent_spawn links parent turn and generates spawn_id
- **WHEN** agent A (in turn_id `T1`) calls `spawn_agent(role='researcher', task='...')` 
- **THEN** an `agent_spawn` event SHALL be emitted with `parent_turn_id='T1'`, `parent_role='A'`, `child_role='researcher'`, and a freshly generated `spawn_id`
- **AND** the spawned child's first `agent_turn` event SHALL have `spawned_by_spawn_id` equal to that `spawn_id`

#### Scenario: pipeline_event emitted at node boundaries
- **WHEN** a pipeline node starts executing
- **THEN** a `pipeline_event` with `pipeline_event_type='node_start'`, `pipeline_name` and `node_name` SHALL be emitted

#### Scenario: error event captures stacktrace hash
- **WHEN** an exception is caught in the LLM call path
- **THEN** an `error` event SHALL be emitted with `source='llm'`, `error_type` set to the exception class, `message` truncated to 500 chars, and `stacktrace_hash` set to the SHA256 of the stacktrace string

### Requirement: Turn linking via contextvars for zero-boilerplate propagation
The telemetry module SHALL define three module-level contextvars in `src/telemetry/collector.py`:
- `current_turn_id: ContextVar[str | None]` — set by `SessionRunner` at turn entry, reset at turn exit
- `current_spawn_id: ContextVar[str | None]` — set by `spawn_agent` tool when emitting its spawn event, inherited by spawned child tasks via `asyncio.create_task` contextvar snapshot
- `current_run_id: ContextVar[str | None]` — set by pipeline execution at run start, reset at run end

All `TelemetryCollector.record_*` methods SHALL automatically read these contextvars and merge their values into the event payload (`turn_id` / `parent_turn_id` / `spawn_id` / `run_id`). Emission sites SHALL NOT need to pass turn/spawn/run identifiers explicitly.

#### Scenario: tool_call inherits turn_id from contextvar
- **WHEN** `SessionRunner` enters a turn with `current_turn_id.set('T1')` and then a tool runs
- **THEN** the `tool_call` event emitted by the hook runner SHALL have `parent_turn_id='T1'` without the hook runner passing it explicitly

#### Scenario: Concurrent spawned children get distinct spawn_ids
- **WHEN** agent A emits two `agent_spawn` events concurrently (two `spawn_agent` calls in parallel tool calls)
- **THEN** each spawned child's first turn SHALL have a distinct `spawned_by_spawn_id`, matching the respective parent spawn event

#### Scenario: Contextvar reset on turn exit prevents leakage
- **WHEN** a `SessionRunner` turn ends (via `done` event or exception)
- **THEN** `current_turn_id` SHALL be reset to its previous value (or None) so subsequent events outside the turn do not inherit a stale `turn_id`

### Requirement: Batched async writer with bounded queue
`TelemetryCollector` SHALL expose synchronous `record_*` methods that append events to an in-memory `asyncio.Queue` with capacity `max_queue_size` (default 10000). A background asyncio task `_writer_loop` SHALL drain the queue and bulk-insert events into `telemetry_events` every `flush_interval_sec` (default 2.0) OR when the queue has `batch_size` (default 100) events, whichever comes first.

When the queue is full, `record_*` SHALL drop the oldest event, insert the new one, and log a WARNING with the count of dropped events since the last WARNING (rate-limited). `record_*` SHALL NOT block.

On FastAPI lifespan shutdown, `TelemetryCollector.stop()` SHALL drain the queue synchronously with a hard timeout of 10 seconds; events still queued after the timeout are lost and a final count is logged.

#### Scenario: Events batched up to flush interval
- **WHEN** 30 events are emitted over 1 second with `flush_interval_sec=2.0` and `batch_size=100`
- **THEN** no PG write SHALL occur until 2 seconds elapse
- **AND** at 2 seconds, a single bulk INSERT SHALL persist all 30 events

#### Scenario: Batch size triggers early flush
- **WHEN** 150 events are emitted in 100ms with `batch_size=100`
- **THEN** a bulk INSERT SHALL fire as soon as the 100th event arrives

#### Scenario: Queue full drops oldest
- **WHEN** the queue is at capacity 10000 and a new event arrives
- **THEN** the oldest event SHALL be removed, the new event SHALL be inserted, and the drop count SHALL increment
- **AND** a WARNING SHALL be logged no more than once per 30 seconds

#### Scenario: Graceful shutdown drains queue
- **WHEN** FastAPI lifespan shutdown calls `collector.stop()` with 50 events in queue
- **THEN** all 50 events SHALL be flushed to PG within 10 seconds (or the remainder logged as lost)

### Requirement: Cost calculation from snapshotted pricing table
`TelemetryCollector` SHALL load a `PricingTable` from `config/pricing.yaml` at construction time. The table SHALL map `(provider, model)` to `{input_usd_per_1k_tokens, output_usd_per_1k_tokens, cache_read_discount_factor}`.

For each `llm_call` event, cost SHALL be calculated as:
```
cost_usd = (
    (input_tokens - cache_read_tokens) * input_usd_per_1k / 1000
    + cache_read_tokens * input_usd_per_1k * cache_read_discount_factor / 1000
    + output_tokens * output_usd_per_1k / 1000
)
```

If `(provider, model)` is not in the pricing table, `cost_usd` SHALL be set to `null` and a WARNING SHALL be logged once per unseen `(provider, model)` pair per collector lifetime.

`config/pricing.yaml` SHALL be a plain, human-editable yaml file with a documented schema (one top-level `models:` key; each entry keyed by `{provider}/{model}` with the three numeric fields). Adding a new model SHALL require only a yaml edit — no code change.

The collector SHALL expose a `reload_pricing()` method that atomically swaps in a fresh `PricingTable` read from `pricing_table_path`. A POST `/api/admin/telemetry/reload-pricing` endpoint SHALL invoke this method so operators can update prices without restarting the server. Existing `cost_usd` values in `telemetry_events` are NEVER retroactively recomputed — only new events use the reloaded prices.

**Provider and model label normalization.** The `provider` and `model` strings used as keys into the pricing table SHALL match the strings used by the LLM router and adapter layer when emitting `llm_call` events. When the router or an adapter uses an internal alias (for example `"openai_compat"` for a proxied OpenAI-compatible endpoint) that alias SHALL either (a) be present as a distinct key in `config/pricing.yaml`, or (b) be normalized to the canonical upstream provider string (e.g., `"openai"`) at emit time — whichever approach is chosen, the emitted `llm_call` event's `payload.provider` and `payload.model` SHALL resolve to a present key in the pricing table for all models that are actually invoked in production.

The responsibility for preventing label mismatches rests on the emit side, not on the query side. Aggregation queries SHALL NOT silently coerce `null` cost values to zero; they SHALL preserve `null` through `SUM`/`AVG` operations (SQL default behavior) so that a missing price is distinguishable from a zero cost.

#### Scenario: Cost computed for known model
- **WHEN** an `llm_call` event is emitted for `(provider='anthropic', model='claude-opus-4-6')` with 1000 input tokens and 500 output tokens, and the pricing table has entries for that model
- **THEN** `cost_usd` SHALL be populated per the formula

#### Scenario: Unknown model yields null cost
- **WHEN** an `llm_call` event is emitted for `(provider='foobar', model='bar-v1')` not in the pricing table
- **THEN** `cost_usd` SHALL be `null`
- **AND** a WARNING SHALL be logged the first time this pair is seen

#### Scenario: Cache-read discount applied
- **WHEN** an event has 1000 input_tokens with 800 cache_read_tokens, and `cache_read_discount_factor=0.1`
- **THEN** cost_usd SHALL reflect 200 full-price input tokens + 800 discounted input tokens + output at full price

#### Scenario: Pricing reload picks up new prices without restart
- **WHEN** `config/pricing.yaml` is edited to add a new model and `POST /api/admin/telemetry/reload-pricing` is called
- **THEN** subsequent `llm_call` events for that model SHALL have `cost_usd` populated per the new entry
- **AND** existing events in `telemetry_events` SHALL retain their original `cost_usd` values

#### Scenario: Proxied OpenAI-compatible model resolves to a pricing entry
- **GIVEN** the LLM router is configured to call a proxied OpenAI-compatible endpoint and emits `llm_call` events
- **WHEN** an `llm_call` event is emitted for a model that the proxy serves
- **THEN** the emitted `payload.provider` and `payload.model` SHALL together resolve to a present key in `config/pricing.yaml`
- **AND** `cost_usd` SHALL be non-null for a successful call

#### Scenario: Aggregation preserves null costs
- **GIVEN** a mix of `llm_call` events in the telemetry table, some with `cost_usd=0.012` and others with `cost_usd=null`
- **WHEN** `GET /api/telemetry/aggregate` computes a windowed cost sum
- **THEN** the sum SHALL treat `null` values as unknown (standard SQL `SUM` behavior) and SHALL NOT implicitly convert them to zero before summing
- **AND** a non-null sum SHALL only reflect events whose cost was computed

### Requirement: Telemetry disabled path is zero-overhead
When `TelemetryConfig.enabled = False`, the `TelemetryCollector.record_*` methods SHALL return immediately after a single boolean check, performing no allocations, no contextvar reads, and no event construction.

A `NullTelemetryCollector` SHALL be provided for tests and environments that wish to disable telemetry entirely without instantiating the full collector. Both disabled paths SHALL produce identical observable behavior (no events in DB, no crashes, no warnings).

#### Scenario: Disabled collector skips event construction
- **WHEN** `TelemetryConfig.enabled = False` and `collector.record_llm_call(...)` is called
- **THEN** the call SHALL return within a single bool-check's time
- **AND** no event SHALL be queued, no contextvar SHALL be read, no payload SHALL be allocated

#### Scenario: Null collector is interchangeable
- **WHEN** production code uses `NullTelemetryCollector` instead of `TelemetryCollector`
- **THEN** all emission call sites SHALL run unchanged with no events persisted

### Requirement: REST query API exposes aggregate views
The telemetry module SHALL expose a FastAPI router mounted under `/api/runs/{run_id}/telemetry` and `/api/sessions/{session_id}/telemetry` with the following endpoints:

- `GET /api/runs/{run_id}/telemetry/summary` — total tokens, cost, duration, event counts by type
- `GET /api/runs/{run_id}/telemetry/timeline` — flat event list sorted by `ts`, for A1 Gantt view
- `GET /api/runs/{run_id}/telemetry/tree` — hierarchical execution tree (A6), built from `agent_turn` + links
- `GET /api/runs/{run_id}/telemetry/agents` — per-agent rollup: tokens, cost, tool count, turn count
- `GET /api/runs/{run_id}/telemetry/errors` — list of `error` events for this run
- `GET /api/sessions/{session_id}/telemetry/summary` — same shape as run summary, session-scoped
- `GET /api/sessions/{session_id}/telemetry/tree` — same shape as run tree, session-scoped
- `GET /api/projects/{project_id}/telemetry/cost` — cost rollup with optional filters `?pipeline=X&from=...&to=...&group_by=day|week|pipeline`
- `GET /api/projects/{project_id}/telemetry/trends` — cross-run LLM latency and token trends over time
- `POST /api/admin/telemetry/reload-pricing` — reload `config/pricing.yaml` into the running collector; returns the count of models loaded

All endpoints SHALL require the existing API key auth (same as other `/api/*` routes). All endpoints SHALL return 404 if the resource (run/session/project) does not exist.

#### Scenario: Run summary returns aggregated metrics
- **WHEN** `GET /api/runs/{run_id}/telemetry/summary` is called for a completed run with 10 llm_calls and 5 tool_calls
- **THEN** the response SHALL include `total_tokens`, `total_cost_usd`, `duration_ms`, and `event_counts={"llm_call":10,"tool_call":5,...}`

#### Scenario: Tree endpoint reconstructs spawn hierarchy
- **WHEN** `GET /api/sessions/{session_id}/telemetry/tree` is called for a session where a coordinator spawned 2 sub-agents
- **THEN** the response SHALL be a nested structure with the coordinator's turn at the root and sub-agent turns as children, linked via `spawn_id`

#### Scenario: Cost rollup groups by day
- **WHEN** `GET /api/projects/{id}/telemetry/cost?group_by=day&from=2026-04-01&to=2026-04-11` is called
- **THEN** the response SHALL be a list of `{date, total_cost_usd, run_count}` entries, one per day

#### Scenario: 404 on missing run
- **WHEN** `GET /api/runs/nonexistent/telemetry/summary` is called
- **THEN** the response SHALL be HTTP 404

### Requirement: TelemetryConfig section in settings
`src/project/config.py` SHALL expose a `TelemetryConfig` pydantic model with fields:
- `enabled: bool = True`
- `preview_length: int = 30`
- `batch_size: int = 100`
- `flush_interval_sec: float = 2.0`
- `max_queue_size: int = 10000`
- `pricing_table_path: str = "config/pricing.yaml"`

These SHALL be overridable via `settings.yaml` under a top-level `telemetry:` key.

#### Scenario: Default config is enabled
- **WHEN** `settings.yaml` has no `telemetry:` section
- **THEN** `Settings.telemetry.enabled` SHALL be `True` and `preview_length` SHALL be `30`

#### Scenario: Override preview length
- **WHEN** `settings.yaml` contains `telemetry.preview_length: 50`
- **THEN** `Settings.telemetry.preview_length` SHALL be `50`

### Requirement: TelemetryCollector depends on EventBus for event fan-out
`TelemetryCollector.__init__` SHALL accept a required `bus: EventBus` parameter. On construction, it SHALL call `bus.subscribe("telemetry", max_size=max_queue_size)` and store the returned queue as `self._queue`. All `record_*` methods SHALL emit events via `self._bus.emit(event)` instead of pushing to a private queue. The `_writer_loop` SHALL drain `self._queue` as before. Public API (`record_llm_call`, `record_tool_call`, `record_agent_turn`, `record_agent_spawn`, `record_pipeline_event`, `record_session_event`, `record_hook_event`, `record_error`, `turn_context`, `reload_pricing`, `start`, `stop`) SHALL remain bit-for-bit unchanged from callers' perspective.

#### Scenario: Collector emits via bus and consumes its own subscribed queue
- **WHEN** `TelemetryCollector(bus=bus, ...)` is constructed and `record_llm_call(...)` is called
- **THEN** the event SHALL arrive in `self._queue` via `bus.emit`
- **AND** `_writer_loop` SHALL drain it on the next flush cycle

#### Scenario: A second subscriber on the same bus receives the event too
- **WHEN** `bus.subscribe("notify")` is called on the same bus the collector uses, and `collector.record_llm_call(...)` is then invoked
- **THEN** the event SHALL appear in BOTH the collector's queue AND the `notify` queue
- **AND** the collector's `_writer_loop` SHALL still flush it to `telemetry_events` normally

#### Scenario: record_* API signature unchanged
- **WHEN** existing Phase 6.2 test scripts call `record_llm_call(provider, model, usage, latency_ms, finish_reason)` with the same arguments as before
- **THEN** the call SHALL succeed with no signature errors
- **AND** the resulting `telemetry_events` row SHALL match the Phase 6.2 expected shape

### Requirement: NullTelemetryCollector does not interact with EventBus
`NullTelemetryCollector` SHALL remain a no-op subclass. Its constructor SHALL NOT subscribe to any bus, and its `record_*` methods SHALL return immediately without calling `bus.emit`. It SHALL accept but ignore any `bus` argument to maintain a uniform construction contract with `TelemetryCollector`.

#### Scenario: Null collector no-op path
- **WHEN** `NullTelemetryCollector(bus=bus)` is constructed and `record_llm_call(...)` is called
- **THEN** the bus SHALL have zero events in any subscriber queue as a result
- **AND** no `telemetry_events` rows SHALL be written

### Requirement: Collector overflow semantics delegated to EventBus
The drop-oldest-with-rate-limited-warning behavior formerly implemented inside `TelemetryCollector._record_safely` SHALL now be enforced by `EventBus.emit`. The observable behavior from Phase 6.2 SHALL be preserved: under queue pressure, the oldest events are dropped, warnings are logged at most once per 10 seconds per subscriber, and no exception is raised into caller code.

#### Scenario: Overflow behavior matches Phase 6.2
- **WHEN** the collector's queue is at `maxsize` and another event is emitted
- **THEN** the oldest event in the collector's queue SHALL be dropped
- **AND** the new event SHALL be enqueued
- **AND** at most one WARNING log SHALL appear within a 10-second cooldown window

