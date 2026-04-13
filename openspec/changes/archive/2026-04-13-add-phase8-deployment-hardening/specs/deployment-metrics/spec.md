## ADDED Requirements

### Requirement: Prometheus-format /metrics endpoint

The FastAPI app SHALL expose a `GET /metrics` route (outside the `/api` prefix, unauthenticated) that returns the current values of all registered collectors in the Prometheus text exposition format, using `Content-Type: text/plain; version=0.0.4; charset=utf-8`. The route SHALL be mounted on `src.main.app` at module import time so it is available as soon as the process accepts HTTP traffic.

#### Scenario: Metrics endpoint returns text format
- **WHEN** a client sends `GET /metrics` to the running API
- **THEN** the response SHALL be HTTP 200 with `Content-Type: text/plain; version=0.0.4; charset=utf-8`
- **AND** the body SHALL contain at least the five metric names: `sessions_active`, `workers_running`, `pg_connections_used`, `sse_connections`, `messages_total`
- **AND** each metric SHALL be preceded by `# HELP <name> ...` and `# TYPE <name> (gauge|counter)` lines

#### Scenario: Metrics endpoint bypasses X-API-Key auth
- **WHEN** `GET /metrics` is called with no `X-API-Key` header
- **THEN** the response SHALL be HTTP 200 (not 401)

#### Scenario: Metrics endpoint is outside /api prefix
- **WHEN** the FastAPI app routes are inspected after startup
- **THEN** `/metrics` SHALL be registered at the root prefix, not under `/api/metrics`

### Requirement: sessions_active gauge reflects SessionRunner registry

The system SHALL expose a `sessions_active` gauge whose value at scrape time equals the number of currently-registered SessionRunner instances in the global session registry. The gauge SHALL be computed via a `set_function` callback against the registry, not incremented/decremented from lifecycle hooks.

#### Scenario: Gauge matches registry count
- **WHEN** three SessionRunner instances are registered and `GET /metrics` is called
- **THEN** the response body SHALL contain the line `sessions_active 3.0` (or `3`, formatter-dependent)

#### Scenario: Gauge decreases after GC
- **WHEN** a SessionRunner is removed from the registry (idle timeout or explicit stop) and `GET /metrics` is called
- **THEN** the `sessions_active` value SHALL reflect the decrement on the very next scrape (no drift, no stale value)

### Requirement: workers_running gauge reflects active agent workers

The system SHALL expose a `workers_running` gauge whose value equals the number of currently-executing agent worker tasks (sub-agent spawns and in-flight pipeline runs) tracked by the worker registry.

#### Scenario: Gauge counts in-flight workers
- **WHEN** two worker tasks are in-flight and `GET /metrics` is called
- **THEN** the response body SHALL contain `workers_running 2.0`

#### Scenario: Gauge drops to zero after completion
- **WHEN** all in-flight workers complete and the registry is empty
- **THEN** the next `GET /metrics` response SHALL contain `workers_running 0.0`

### Requirement: pg_connections_used gauge reflects SQLAlchemy pool state

The system SHALL expose a `pg_connections_used` gauge that reports the number of connections currently checked out from the SQLAlchemy engine's connection pool (NOT the total pool size, NOT the number of idle connections). The value SHALL be obtained via `engine.pool.checkedout()` at scrape time.

#### Scenario: Gauge reflects checked-out connections
- **WHEN** a request handler holds an open database session and `GET /metrics` is called concurrently
- **THEN** the `pg_connections_used` value SHALL be at least 1

#### Scenario: Gauge returns to zero when all sessions released
- **WHEN** all request handlers have released their sessions back to the pool and `GET /metrics` is called
- **THEN** the `pg_connections_used` value SHALL be 0

### Requirement: sse_connections gauge reflects active SSE subscribers

The system SHALL expose an `sse_connections` gauge whose value equals the number of currently-open SSE long-poll connections across all endpoints (`/api/sessions/*/events`, `/api/runs/*/stream`, `/api/notify/stream`). The value SHALL come from the SSE handler's active-subscriber registry.

#### Scenario: Gauge increments on new SSE connection
- **WHEN** a client opens an SSE connection to any `/api/*/stream`-style endpoint
- **THEN** the next `GET /metrics` response SHALL reflect one additional active connection

#### Scenario: Gauge decrements on disconnect
- **WHEN** an SSE client disconnects (cleanly or via `asyncio.CancelledError`)
- **THEN** the next `GET /metrics` response SHALL reflect one fewer active connection

### Requirement: messages_total counter tracks bus publish volume

The system SHALL expose a `messages_total` counter that is incremented by 1 every time a message is successfully published to the internal event bus (`src.event_bus.bus.publish`). This counter SHALL be monotonically increasing and never reset at runtime. Failed publishes (exceptions raised before the subscribers receive the message) SHALL NOT increment the counter.

#### Scenario: Counter increments on publish
- **WHEN** 10 messages are published to the event bus
- **THEN** the `messages_total` value in the next scrape SHALL be at least 10 greater than the previous scrape value

#### Scenario: Counter never decreases
- **WHEN** two successive `GET /metrics` calls are made
- **THEN** the second `messages_total` value SHALL be >= the first (counters are monotonic)

### Requirement: Metrics collectors registered at app startup

All five collectors SHALL be registered in a single `src/api/metrics.py` module that is imported by `src/main.py` during app construction. The module SHALL expose:
- A module-level `CollectorRegistry` (may reuse `prometheus_client.REGISTRY` as default)
- A `setup_metrics(app, engine, session_registry, worker_registry, sse_registry)` function that binds callbacks to the provided registries
- A `metrics_endpoint()` function returning `Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)`

#### Scenario: Metrics module imports cleanly
- **WHEN** `src.api.metrics` is imported
- **THEN** the import SHALL succeed without side effects beyond defining functions and the shared registry

#### Scenario: setup_metrics wires all five collectors
- **WHEN** `setup_metrics` is called with valid registry references
- **THEN** subsequent `generate_latest()` output SHALL include all five metric names
