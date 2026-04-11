# Event Bus

## Purpose
Provide a minimal in-process event fan-out primitive that decouples event producers (telemetry collector, session runner, hooks) from event consumers (writer loops, SSE streams, notifiers). The bus is a pure data structure: a subscriber list plus a synchronous, non-blocking emit. It owns no background tasks and applies drop-oldest overflow with rate-limited warnings so a slow consumer cannot stall producers or affect other subscribers.

## Requirements

### Requirement: EventBus provides per-subscriber queue fan-out
The system SHALL provide an `EventBus` class in `src/events/bus.py` that supports multiple independent subscribers, each receiving events through its own `asyncio.Queue`. `EventBus.subscribe(name: str, max_size: int | None = None) -> asyncio.Queue` SHALL return a new queue on each call. The caller SHALL own the returned queue and be responsible for consuming from it.

#### Scenario: Two subscribers receive the same event
- **WHEN** two consumers call `bus.subscribe("a")` and `bus.subscribe("b")` and then `bus.emit(event)` is called once
- **THEN** both queues SHALL receive the event exactly once

#### Scenario: Subscribe returns distinct queues
- **WHEN** `bus.subscribe("x")` is called twice
- **THEN** the two returned queue objects SHALL be different instances
- **AND** events emitted after the second subscribe SHALL be fanned out to both queues

#### Scenario: Custom per-subscriber max_size
- **WHEN** `bus.subscribe("t", max_size=500)` is called
- **THEN** the returned queue SHALL have `maxsize == 500`
- **AND** other subscribers with default size SHALL be unaffected

### Requirement: emit is synchronous and non-blocking
`EventBus.emit(event: object) -> None` SHALL be a synchronous method that returns in O(number of subscribers). It SHALL NOT await, SHALL NOT raise on full queues, and SHALL NOT block the caller.

#### Scenario: emit does not await
- **WHEN** code inside a synchronous function calls `bus.emit(event)`
- **THEN** the call SHALL return without requiring `await`
- **AND** the subscriber queues SHALL contain the event before the next statement runs

#### Scenario: emit with zero subscribers is a no-op
- **WHEN** `bus.emit(event)` is called and no subscribers exist
- **THEN** the call SHALL return normally without error

### Requirement: Overflow uses drop-oldest with rate-limited warning
When a subscriber queue is full during `emit`, the bus SHALL drop the oldest event from that queue and enqueue the new event. It SHALL log a `WARNING` naming the subscriber and including a dropped-count since the last warning, rate-limited to at most one warning per 10 seconds per subscriber. Other subscribers SHALL NOT be affected.

#### Scenario: Full queue drops oldest on next emit
- **WHEN** a subscriber queue has `maxsize=3` and 4 events are emitted in sequence
- **THEN** the queue SHALL contain exactly the last 3 events
- **AND** the first event SHALL have been dropped

#### Scenario: One subscriber full does not affect others
- **WHEN** subscriber A has a full queue and subscriber B has a non-full queue, and `bus.emit(event)` is called
- **THEN** subscriber B SHALL receive the event with no drop
- **AND** subscriber A SHALL drop its oldest and receive the new event

#### Scenario: Warning is rate-limited per subscriber
- **WHEN** 100 events are dropped from subscriber A's queue within 1 second
- **THEN** at most 1 WARNING SHALL be logged for subscriber A
- **AND** subsequent drops within the 10-second cooldown SHALL be counted but not logged individually

### Requirement: EventBus close terminates further emission
`EventBus.close() -> None` (sync) or `await EventBus.aclose()` SHALL mark the bus closed. After close, `emit` SHALL become a no-op (not raise). Pre-close events already placed on subscriber queues SHALL remain consumable so consumers can drain on shutdown.

#### Scenario: Emit after close is no-op
- **WHEN** `bus.close()` is called and then `bus.emit(event)` is called
- **THEN** no exception SHALL be raised
- **AND** no subscriber queue SHALL receive the event

#### Scenario: Drain existing events after close
- **WHEN** 5 events are emitted, then `bus.close()` is called, then the subscriber drains its queue
- **THEN** the subscriber SHALL be able to read all 5 pre-close events from its queue

### Requirement: Bus does not own background tasks
`EventBus` SHALL NOT start any `asyncio.Task` internally. Consumers SHALL be responsible for starting their own consumption loops. The bus itself is a pure data structure: a subscriber list and a stateless fan-out method.

#### Scenario: Bus construction does not schedule tasks
- **WHEN** `EventBus(queue_size=1000)` is constructed
- **THEN** no new `asyncio.Task` SHALL exist as a result of the construction
- **AND** `asyncio.all_tasks()` SHALL contain no task owned by the bus
