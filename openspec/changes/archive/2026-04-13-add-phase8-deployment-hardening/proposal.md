## Why

Phase 7 shipped a working compose stack and an end-to-end smoke test, but three deployment-side risks from `.plan/rest_api_deployment_risks.md` are still open and will bite the first time a real user runs this on a server: (1) the SQLAlchemy connection pool is still at the library default (5+10) which will stall under modest concurrency, (2) nginx will chop SSE review-interrupt connections after 60 seconds of idle even though the code already emits heartbeats, and (3) the service has no operational visibility at all — when something stalls, the only tool is log-grepping. This change closes all three in one pass so Phase 8 is actually "deployable" and not just "runnable".

## What Changes

- **PG connection pool**: raise SQLAlchemy engine defaults in `src/db.py` (pool_size 20, max_overflow 40, pool_pre_ping on), make them settings-driven so ops can tune without code changes. Enforce the "`pool_size × workers ≤ max_connections - reserved`" invariant via a startup sanity check.
- **nginx SSE config**: add a dedicated `location /api/sessions/` block in `web/nginx.conf` with `proxy_read_timeout 3600s`, `proxy_buffering off`, `proxy_cache off`, and `X-Accel-Buffering: no` passthrough so review interrupts can park indefinitely without the proxy cutting the connection. Also enforce `workers 1` (single API worker) as a hard invariant with a startup log warning if the env tries to override it — risk #1 from the deployment doc is explicitly out of scope and single-worker is the contract.
- **`/metrics` endpoint**: new `deployment-metrics` capability. Expose a Prometheus-format text endpoint at `GET /metrics` (unauthenticated, localhost-bindable via config) serving 5 core gauges/counters:
  - `sessions_active` (gauge) — from SessionRunner registry
  - `workers_running` (gauge) — from worker registry
  - `pg_connections_used` (gauge) — from SQLAlchemy pool introspection
  - `sse_connections` (gauge) — from SSE handler registry
  - `messages_total` (counter) — incremented per published bus message
- **Prometheus + Grafana services**: add two new docker-compose services gated behind a `monitoring` profile (so default `docker compose up` does NOT start them; `docker compose --profile monitoring up` does). Ship a pre-provisioned Grafana dashboard JSON with the 5 metrics + a data source pointing at the bundled Prometheus.
- Update `README.md` with a short "Monitoring" section explaining how to opt in and where the dashboard lives.
- **Out of scope** (explicitly deferred, documented in design.md): multi-worker session routing (risk #1 from rest_api_deployment_risks.md — we keep single-worker as a hard constraint), PG index optimization (risk #3), cross-restart in-flight worker recovery (risk #5), business-level metrics (user activity / pipeline popularity / agent call counts).

## Capabilities

### New Capabilities
- `deployment-metrics`: Prometheus-format operational metrics endpoint for the API service, covering concurrency (active sessions, running workers, SSE connections), resource saturation (DB pool usage), and throughput (bus message counter). Defines the exact metric names, types, label cardinality, scrape endpoint path, and startup/shutdown registration lifecycle.

### Modified Capabilities
- `rest-api`: adds the `/metrics` endpoint route + settings-driven PG pool size + single-worker startup invariant check.
- `docker-compose-stack`: adds the `monitoring` compose profile with `prometheus` + `grafana` services, updates `web/nginx.conf` with the `/api/sessions/` SSE-safe location block.

## Impact

- **Code**: `src/db.py` (pool sizing + sanity check), `src/api/metrics.py` (new file, registers collectors against the existing SessionRunner/worker registries and SQLAlchemy engine), `src/api/app.py` (mount /metrics), `src/api/events.py` or equivalent (SSE connection gauge hook), `src/event_bus/*` (messages_total counter hook).
- **Config**: `config/settings.yaml` gains `database.pool_size` / `database.max_overflow` / `database.pool_pre_ping`; `config/project/config.py` adds a `DatabaseConfig` dataclass.
- **Infra**: `docker-compose.yaml` gains `prometheus` + `grafana` services under `profiles: [monitoring]`. New files `deploy/prometheus.yml`, `deploy/grafana/provisioning/datasources/datasource.yml`, `deploy/grafana/provisioning/dashboards/dashboards.yml`, `deploy/grafana/dashboards/mas-pipeline.json`. `web/nginx.conf` gains the SSE location block.
- **Dependencies**: `prometheus-client` (official Python lib) added to `requirements.txt`.
- **Docs**: `README.md` gets a "Monitoring (optional)" section. `docs/architecture.md` (if it exists — Phase 8.5 work) will reference the metrics capability.
- **Backward compat**: default `docker compose up` behavior unchanged (monitoring profile is opt-in); existing deployments that override `database.pool_size` via env continue to work; `/metrics` is a new route, no collisions.
