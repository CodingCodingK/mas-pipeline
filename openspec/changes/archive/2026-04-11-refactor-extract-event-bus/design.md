## Context

Phase 6.2 delivered the telemetry pipeline (`src/telemetry/collector.py`) with a single `asyncio.Queue` owned privately by `TelemetryCollector`. Business code across pipeline / session_runner / agent_loop / hooks / spawn_agent / gateway emits events via `get_collector().record_*()` facades. A background `_writer_loop` task drains the queue in batches to `telemetry_events` PG table.

Phase 6.3 adds a Notifier with 3 channels (SSE / wechat / discord) that needs to observe the exact same event stream and derive notifications via rules. Telemetry's responsibility is "append-only observability store" — it should not grow a public fan-out hook or subscriber registry, because that would blur its role and create an implicit event-bus-inside-a-sink. Future work (metrics rollup, audit log, replay) will introduce even more consumers, so the abstraction needs a real home.

The EventBus is that home. This refactor is pure plumbing: no new business behavior, no new persisted data, no new external API. The gate is a zero-regression run of the Phase 6.2 test surface (6 telemetry test scripts, 109 checks).

## Goals / Non-Goals

**Goals:**
- Extract a minimal shared in-process `EventBus` with strict per-subscriber queue isolation
- Keep `TelemetryCollector`'s public API (all 8 `record_*` methods, `turn_context`, `start`, `stop`, `reload_pricing`) bit-for-bit unchanged
- Leave every Phase 6.2 Layer 1 emission site (pipeline / session_runner / agent_loop / hooks / spawn_agent / gateway) untouched
- Preserve Phase 6.2 overflow semantics (drop-oldest + rate-limited warning) by hoisting them from collector into bus
- Maintain single-event-loop, single-process assumptions — no cross-process pub/sub, no Redis yet
- Pass all 6 Phase 6.2 telemetry test scripts with only fixture-level changes (construct `EventBus` and pass to collector)

**Non-Goals:**
- Adding Notifier, channels, rules, or preferences — that's change #2 (`add-notify-layer`)
- Cross-process fan-out (future work, would introduce Redis pub/sub)
- Generic typed event schema — bus is intentionally untyped at the fan-out layer, consumers cast
- Refactoring emission sites or changing `get_collector()` contextvar facade
- Migrating persisted `telemetry_events` rows or touching DB schema
- Backpressure beyond drop-oldest (no `put_nowait` replacement, no adaptive flow control)

## Decisions

### Decision 1: Per-subscriber queue, not shared queue

**Choice:** Each `bus.subscribe(name)` returns a **new** `asyncio.Queue` owned by the caller. `bus.emit(event)` iterates the subscriber list and calls `put_nowait` on each queue.

**Why:** A shared queue with central dispatch forces dispatch to `await consumer.handle(event)` for each consumer, which means a slow consumer (e.g., notifier doing Discord webhook IO) would block telemetry's DB writes and vice versa. Per-subscriber queues give strict isolation: one consumer backing up, crashing, or blocking never affects the others. Memory cost is trivial (~10k slots × 2 consumers = 20k object refs).

**Alternatives considered:**
- Shared queue + central dispatch loop: rejected for isolation reasons above
- Callback fan-out (bus calls subscriber callables directly in emit): rejected because emit must stay synchronous O(1), and callbacks would either run inline (blocks) or spawn tasks (unbounded task creation)
- Broadcast stream (`asyncio.StreamReader` / anyio.MemoryObjectStream): rejected as overkill — we already have `asyncio.Queue` semantics everywhere else in the codebase

### Decision 2: `emit()` is synchronous and O(1)

**Choice:** `bus.emit(event)` is a regular (non-async) method that calls `put_nowait` on each subscriber queue. It never awaits. If a queue is full, it drops the oldest event and logs a rate-limited warning.

**Why:** Phase 6.2's `record_*()` facade is synchronous — called from synchronous code paths (e.g., inside `record_pipeline_event` called from a sync decorator). Making emit async would ripple up and force every caller to await, which would change the facade signature and force changes to every emission site. Synchronous emit preserves the Phase 6.2 API contract entirely.

The overflow policy is lifted from Phase 6.2's `collector._record_safely` helper verbatim — drop-oldest + `logger.warning` with a rate-limit cooldown per subscriber. This guarantees the runtime behavior under pressure is identical to Phase 6.2.

**Alternatives considered:**
- Async `emit` with `put` and backpressure: rejected — would force facade async, cascade change
- Dropping new events on overflow: rejected — contradicts Phase 6.2 behavior, loses recent events which are typically the most important
- Unbounded queues: rejected — trades bounded memory loss for unbounded memory growth under misbehavior

### Decision 3: `TelemetryCollector` keeps its facade, internally switches to `bus.emit`

**Choice:** The constructor gains a required `bus: EventBus` parameter. Internally, `self._queue = bus.subscribe("telemetry")` replaces the old private queue construction. All `record_*` methods' body change from `self._queue.put_nowait(event)` (and its overflow wrapping) to `self._bus.emit(event)`. `_writer_loop` still reads from `self._queue`, because `subscribe()` returns the queue it'll be consuming.

**Why:** Preserves the facade contract for business code. `self._bus.emit` handles the overflow logic centrally, so `_record_safely` in the collector collapses to a simple `if enabled: bus.emit(build_event())`. Both simpler and more consistent.

**Alternatives considered:**
- Keep collector's own queue and additionally fan-out to a bus inside `_record_safely`: rejected — that's the Path Z (B1) design that blurs telemetry's role, which is the whole reason for the refactor
- Make the bus a module-level singleton like `get_collector()`: rejected — explicit injection via FastAPI lifespan is cleaner for tests (easy to construct a fresh bus per test case) and matches how telemetry already gets its `db_session_factory`

### Decision 4: Queue size is per-subscriber, configured via constructor

**Choice:** `EventBus(queue_size: int = 10000)` sets the default; `bus.subscribe(name, max_size: int | None = None)` can override per-subscriber. `TelemetryCollector` passes the `max_queue_size` from its existing `TelemetryConfig` field into `subscribe("telemetry", max_size=...)`.

**Why:** Different consumers have different flow rates. Telemetry writes 10-100 events/sec in batches; a notifier with HTTP webhooks writes 1-10/sec. Letting each subscriber right-size its own buffer avoids either over-reserving for low-rate consumers or under-buffering high-rate ones. The collector's existing config key `telemetry.max_queue_size` keeps its meaning (queue feeding the collector's writer loop), so no config migration.

### Decision 5: `NullTelemetryCollector` does not touch the bus

**Choice:** `NullTelemetryCollector` remains a subclass with no-op `record_*` and `start`/`stop`. It does NOT subscribe to the bus. Its constructor ignores any passed bus argument.

**Why:** The null collector exists precisely for the "telemetry disabled" path where we want zero overhead. Making it subscribe and then drop everything would defeat the point. Business code paths check `get_collector()` and call `record_*` without knowing the implementation — null's no-op methods short-circuit before any bus interaction.

### Decision 6: No task started inside `EventBus` itself

**Choice:** `EventBus` has no background task. It's purely a data structure: a list of subscribers and a stateless fan-out method. Consumers are responsible for starting their own loops via their own `start()` methods.

**Why:** Keeps ownership obvious. Each consumer's lifecycle (start, stop, drain, error handling) lives in the consumer class. A bus that owned tasks would have to coordinate shutdown across consumers it doesn't own, adding coupling. This also matches Phase 6.2's collector structure exactly — `collector.start()` spawns `_writer_loop`; nothing else.

## Risks / Trade-offs

- **[Risk] Test fixture churn across 6 Phase 6.2 test scripts** → Mitigation: create a tiny `_make_bus_and_collector()` helper in each script; all 6 scripts follow the same pattern. Actual churn is ≤ 3 lines per script.
- **[Risk] Hidden ordering assumption — consumers might implicitly expect events in a specific arrival order** → Mitigation: bus preserves order per subscriber (queues are FIFO). Across subscribers, order is not guaranteed, but no Phase 6.2 code or Phase 6.3 plan relies on cross-subscriber ordering.
- **[Risk] Forgot-to-start consumer silently swallows events** → Mitigation: bus logs a warning at `subscribe()` time if the subscriber is created but no `Queue.get()` is ever called within N seconds; also covered by integration test that asserts zero-drop under normal rates.
- **[Risk] Overflow warning spam during load spikes** → Mitigation: per-subscriber rate-limit of 1 warning per 10 seconds, same cooldown Phase 6.2 uses for collector's drop-oldest warning.
- **[Risk] Integration test flake due to timing** → Mitigation: tests explicitly `await asyncio.sleep(flush_interval * 2)` after emission before asserting row counts, same pattern as Phase 6.2 integration tests.
- **[Trade-off] Bus is in-process only** → If we ever want multi-worker deployment, we need a cross-process transport (Redis pub/sub, NATS, Kafka). Out of scope for this refactor. The interface is small enough to swap the transport without touching consumers.
- **[Trade-off] Bus is untyped** → `emit(event: object)` accepts anything. Consumers must trust upstream to emit known types or cast defensively. Chosen for simplicity; typed dispatch can be added later without breaking API.

## Migration Plan

1. Implement `src/events/bus.py` with unit tests against pure queue semantics
2. Modify `src/telemetry/collector.py` constructor to require `bus` parameter
3. Rewrite the 6 Phase 6.2 telemetry test scripts' fixture helpers to construct bus + collector together
4. Run full Phase 6.2 telemetry test surface — must stay green
5. Update `src/main.py` lifespan to construct bus → collector → start in order; stop collector → close bus in reverse
6. Run regression suite (session_runner, gateway, rest_api integration) to confirm no externally-observable change
7. Commit + archive

No feature flags, no schema migrations, no rollback steps beyond `git revert` of the single commit.

## Open Questions

- None. The refactor is small and entirely internal.
