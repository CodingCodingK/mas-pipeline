## ADDED Requirements

### Requirement: /metrics endpoint mounted at root prefix

The FastAPI app in `src/main.py` SHALL register the `/metrics` route (defined by the `deployment-metrics` capability) at the root prefix, NOT under `/api`. The route SHALL be exempt from the `X-API-Key` auth dependency. Ordering in `src/main.py` SHALL place the metrics route registration after `/health` and before the versioned `/api` router include so both unauthenticated root-prefix routes are colocated.

#### Scenario: Metrics route registered at root
- **WHEN** the app starts up
- **THEN** `/metrics` SHALL appear in `app.routes` as a route NOT prefixed with `/api`

#### Scenario: Metrics route bypasses auth middleware
- **WHEN** the API key auth dependency is active and `GET /metrics` is called without the header
- **THEN** the response SHALL be HTTP 200

### Requirement: Database connection pool size configurable via settings

The SQLAlchemy engine construction in `src/db.py` SHALL read `database.pool_size`, `database.max_overflow`, and `database.pool_pre_ping` from settings and pass them to `create_engine`. Defaults SHALL be `pool_size=20`, `max_overflow=40`, `pool_pre_ping=True`. Settings SHALL be loadable from `config/settings.yaml` and overridable via environment variables (`DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_PRE_PING`).

#### Scenario: Default pool size applied
- **WHEN** the app starts with no `database.*` overrides
- **THEN** `engine.pool.size()` SHALL return 20 and `engine.pool._max_overflow` SHALL be 40

#### Scenario: Settings override applies
- **WHEN** `config/settings.yaml` contains `database: {pool_size: 50, max_overflow: 100}`
- **THEN** `engine.pool.size()` SHALL return 50 and the max overflow SHALL be 100

#### Scenario: Env override takes precedence
- **WHEN** `DATABASE_POOL_SIZE=30` is set and the app starts
- **THEN** `engine.pool.size()` SHALL return 30 regardless of the YAML value

### Requirement: Startup sanity check against PostgreSQL max_connections

At app startup, after the engine is created but before accepting traffic, `src/db.py` SHALL execute `SHOW max_connections` against the database and compare it against `pool_size + max_overflow`. If the effective pool (`pool_size + max_overflow`) exceeds `max_connections - 10`, the app SHALL emit a WARNING log entry containing both numbers. The app SHALL NOT fail to start in this case — the check is informational only.

#### Scenario: Safe pool size produces no warning
- **WHEN** PG `max_connections=100` and effective pool is 60
- **THEN** no WARNING about pool oversubscription SHALL be logged

#### Scenario: Oversubscribed pool produces warning
- **WHEN** PG `max_connections=50` and effective pool is 60
- **THEN** a WARNING log SHALL be emitted naming both values, and the app SHALL still start

### Requirement: Single-worker startup invariant

The app SHALL enforce single-worker operation at startup. `src/main.py` (or the uvicorn launch path) SHALL read the worker count (from `UVICORN_WORKERS` env var or equivalent). If the worker count is greater than 1, the app SHALL log a CRITICAL error explaining that SessionRunner requires single-worker operation and SHALL exit with a non-zero status code BEFORE accepting traffic. Uvicorn's `--reload` mode (which does not spawn additional workers) SHALL NOT trigger the check.

#### Scenario: Single worker passes
- **WHEN** the app starts with default worker count (1)
- **THEN** startup SHALL proceed normally and the app SHALL accept traffic

#### Scenario: Multi-worker rejected
- **WHEN** the app is launched with `UVICORN_WORKERS=4`
- **THEN** a CRITICAL log SHALL be emitted explaining the constraint
- **AND** the process SHALL exit with a non-zero code before binding the listening socket

#### Scenario: Reload mode passes
- **WHEN** the app starts under `uvicorn --reload` (no `--workers` flag)
- **THEN** startup SHALL proceed normally
