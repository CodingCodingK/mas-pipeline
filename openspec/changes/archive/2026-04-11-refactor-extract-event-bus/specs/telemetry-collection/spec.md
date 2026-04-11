## ADDED Requirements

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
