## Why

Phase 6.2 landed telemetry with an internal single-consumer queue inside `TelemetryCollector`. Phase 6.3 needs a second consumer (Notifier) for real-time UI push + wechat/discord webhooks, and future work will add more (metrics, audit). Letting Notifier subscribe to telemetry's private queue would blur telemetry's "observability store" responsibility into an event bus. Extracting a shared `EventBus` preserves telemetry's role as a pure consumer, lets Notifier and telemetry be peer subscribers, and keeps the business code emission surface unchanged.

## What Changes

- Introduce `src/events/bus.py` as a minimal in-process fan-out router with per-subscriber `asyncio.Queue`s, `bus.subscribe(name) -> Queue`, and synchronous O(1) `bus.emit(event)` with drop-oldest overflow + rate-limited warning
- Refactor `TelemetryCollector.__init__` to take an `EventBus`, subscribe to its own queue under the name `"telemetry"`, and emit via `self._bus.emit(event)` instead of pushing to a private queue
- `TelemetryCollector` public API (`record_llm_call`, `record_tool_call`, `record_agent_turn`, `record_agent_spawn`, `record_pipeline_event`, `record_session_event`, `record_hook_event`, `record_error`, `turn_context`, `reload_pricing`, `start`, `stop`) is **unchanged** — business callers stay as-is
- `NullTelemetryCollector` stays a no-op subclass and does not touch the bus
- `src/main.py` FastAPI lifespan constructs the `EventBus` first, passes it to `TelemetryCollector`, then calls `start()` on both; shutdown order is reversed
- All Phase 6.2 telemetry tests continue to pass with a 1-line fixture change (construct a `TelemetryCollector` with an `EventBus` instance)
- No behavior change observable from pipeline / session_runner / agent_loop / hooks / spawn_agent / gateway — this is a pure internal refactor

## Capabilities

### New Capabilities
- `event-bus`: In-process fan-out event router that multiple independent consumers (telemetry, notify, future metrics/audit) can subscribe to. Defines subscribe/emit/close contract, per-subscriber queue isolation, overflow behavior, and lifespan semantics.

### Modified Capabilities
- `telemetry-collection`: `TelemetryCollector` internal wiring changes from "owns a private queue" to "subscribes to a shared bus". Public record_* API, event types, query layer, REST layer, pricing, contextvars, and persisted rows are all unchanged. The only requirement-level change is that the collector now **depends on** an `EventBus` being available at construction time.

## Impact

- **New files**: `src/events/__init__.py`, `src/events/bus.py`, `scripts/test_event_bus.py`
- **Modified**: `src/telemetry/collector.py` (constructor + internal emit path), `src/main.py` (lifespan wiring), all 6 Phase 6.2 telemetry test scripts (fixture: construct `EventBus` and pass to collector)
- **Unchanged**: all Layer 1 emission sites — `src/agent/loop.py`, `src/hooks/runner.py`, `src/engine/session_runner.py`, `src/engine/pipeline.py`, `src/engine/graph.py`, `src/tools/builtins/spawn_agent.py`, `src/bus/gateway.py`; all other telemetry files (`events.py`, `pricing.py`, `query.py`, `api.py`)
- **External API**: zero change to REST endpoints, DB schema, config keys
- **Regression risk**: low — pure internal wiring swap. Phase 6.2 test surface (109 checks) is the primary gate. No migration needed.
