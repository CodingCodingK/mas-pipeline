## 1. EventBus module

- [x] 1.1 Create `src/events/__init__.py` exporting `EventBus`
- [x] 1.2 Create `src/events/bus.py` with:
  - `EventBus(queue_size: int = 10000)` constructor storing default size + subscriber list + closed flag + per-subscriber warn-cooldown timestamps
  - `subscribe(name: str, max_size: int | None = None) -> asyncio.Queue` appending `(name, queue)` to subscriber list and returning the queue
  - `emit(event: object) -> None` synchronous fan-out: iterate subscribers, `put_nowait`, on `QueueFull` do drop-oldest + rate-limited `logger.warning` (10s cooldown per subscriber)
  - `close() -> None` sets `_closed = True`; post-close `emit` is no-op; pre-close queued events remain consumable
  - Module-level `logger = logging.getLogger(__name__)`
- [x] 1.3 Write `scripts/test_event_bus.py` covering:
  - Two subscribers each receive the same event
  - `subscribe` returns distinct queues
  - Custom `max_size` per subscriber
  - `emit` is synchronous (no `await` needed); zero-subscribers no-op
  - Drop-oldest behavior when a queue is full
  - One full subscriber does not affect others
  - Warning rate-limited to ≤1 per 10s per subscriber
  - Close makes `emit` a no-op but leaves pre-close events drainable
  - Bus construction does not schedule any `asyncio.Task`
- [x] 1.4 Run `python scripts/test_event_bus.py` — all checks must pass

## 2. TelemetryCollector refactor

- [x] 2.1 Modify `src/telemetry/collector.py`:
  - Import `from src.events.bus import EventBus`
  - `TelemetryCollector.__init__` gains required `bus: EventBus` parameter (placed after `db_session_factory`)
  - Replace private `self._queue = asyncio.Queue(maxsize=max_queue_size)` with `self._queue = bus.subscribe("telemetry", max_size=max_queue_size)`
  - Store `self._bus = bus`
  - Delete the inline drop-oldest / cooldown logic inside `_record_safely` (now enforced by `bus.emit`); the helper collapses to `if self._enabled: self._bus.emit(event)`
  - All `record_*` methods' bodies unchanged apart from calling the simplified `_record_safely`
  - `_writer_loop` body unchanged — still reads from `self._queue`
  - `start` / `stop` / `turn_context` / `reload_pricing` unchanged
- [x] 2.2 Modify `NullTelemetryCollector` to accept but ignore a `bus` kwarg; ensure constructor does NOT subscribe; `record_*` remain no-ops
- [x] 2.3 Update `src/telemetry/__init__.py` if any re-exports need adjusting (likely none)

## 3. FastAPI lifespan wiring

- [x] 3.1 Modify `src/main.py` lifespan:
  - Import `from src.events.bus import EventBus`
  - Construct `bus = EventBus(queue_size=settings.telemetry.max_queue_size)` BEFORE telemetry
  - Store `app.state.event_bus = bus`
  - Pass `bus=bus` into `TelemetryCollector(...)` (or `NullTelemetryCollector(bus=bus)` when disabled)
  - On shutdown: call `await collector.stop(timeout_seconds=...)` then `bus.close()` in `finally`

## 4. Test fixture updates (Phase 6.2 regression gate)

- [x] 4.1 `scripts/test_telemetry_collector.py` — add a helper `_make_collector()` that constructs a fresh `EventBus` and passes it to `TelemetryCollector`; update every collector construction site to use it
- [x] 4.2 `scripts/test_telemetry_contextvars.py` — same helper pattern
- [x] 4.3 `scripts/test_telemetry_query.py` — same helper pattern (if it constructs collectors)
- [x] 4.4 `scripts/test_telemetry_api.py` — if it constructs collectors (mostly uses mocks), update fixture
- [x] 4.5 `scripts/test_telemetry_integration.py` — update `_make_collector()` helper to construct `EventBus` alongside
- [x] 4.6 `scripts/test_telemetry_rest_integration.py` — update `_seed_run` helper to construct `EventBus` alongside

## 5. Verification

- [x] 5.1 Run `scripts/test_event_bus.py` — new unit tests green
- [x] 5.2 Run `scripts/test_telemetry_collector.py` — all Phase 6.2 collector checks green
- [x] 5.3 Run `scripts/test_telemetry_contextvars.py` — green
- [x] 5.4 Run `scripts/test_telemetry_query.py` — green
- [x] 5.5 Run `scripts/test_telemetry_api.py` — green
- [x] 5.6 Run `scripts/test_telemetry_integration.py` — graceful-skip or green against live PG
- [x] 5.7 Run `scripts/test_telemetry_rest_integration.py` — graceful-skip or green against live PG
- [x] 5.8 Run regression suite: `scripts/test_session_runner.py`, `scripts/test_streaming_regression.py`, `scripts/test_claw_gateway.py`, `scripts/test_bus_session_runner_integration.py`, `scripts/test_rest_api_integration.py`, `scripts/test_rest_api_auth.py`, `scripts/test_rest_api_sse_backfill.py` — all green

## 6. Validation and archive

- [ ] 6.1 Run `openspec validate refactor-extract-event-bus --strict`
- [ ] 6.2 Update `.plan/progress.md` noting EventBus extracted (Phase 6.3 prep step 1 of 2)
- [ ] 6.3 `git add` + commit
- [ ] 6.4 Run `/openspec-archive-change refactor-extract-event-bus`
