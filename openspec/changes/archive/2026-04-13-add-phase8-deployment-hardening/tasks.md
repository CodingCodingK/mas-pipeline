## 1. PG connection pool hardening

- [x] 1.1 Add `DatabaseConfig` dataclass to `src/project/config.py` (or wherever settings live) with fields `pool_size: int = 20`, `max_overflow: int = 40`, `pool_pre_ping: bool = True`, loaded from `config/settings.yaml` under a `database:` block with env override fallback (`DATABASE_POOL_SIZE` etc.)
- [x] 1.2 Update `config/settings.yaml` with the new `database:` block using the defaults above (commented with a one-line explainer)
- [x] 1.3 Update `src/db.py` `create_engine` call to pass `pool_size`, `max_overflow`, `pool_pre_ping` from the settings
- [x] 1.4 Add a `check_pool_sizing()` helper in `src/db.py` that runs `SHOW max_connections` against the engine after construction and logs a WARNING if `pool_size + max_overflow > max_connections - 10`. Call it from app startup (lifespan context in `src/main.py`)
- [x] 1.5 Add unit test `scripts/test_db_pool.py` that verifies: (a) defaults are applied when no settings override, (b) YAML override takes effect, (c) env override beats YAML, (d) the sanity check logs a warning but does not raise when oversubscribed

## 2. Single-worker startup invariant

- [x] 2.1 Add a `check_single_worker()` function in `src/main.py` that inspects `os.environ.get("UVICORN_WORKERS", "1")` — if > 1, log CRITICAL and `sys.exit(1)` before the lifespan enters. Import it and call it at module load (or lifespan startup, whichever runs before binding the socket)
- [x] 2.2 Verify uvicorn `--reload` does not set `UVICORN_WORKERS` — document in a code comment
- [x] 2.3 Unit test (extend `scripts/test_db_pool.py` or add `scripts/test_worker_invariant.py`): patch the env, call the check, assert it raises `SystemExit` on `UVICORN_WORKERS=4` and returns normally on `UVICORN_WORKERS=1`

## 3. Metrics module (`src/api/metrics.py`)

- [x] 3.1 Add `prometheus-client` to `requirements.txt` (pin a recent version, e.g. `prometheus-client==0.20.0`)
- [x] 3.2 Create `src/api/metrics.py` defining five collectors: `sessions_active` / `workers_running` / `pg_connections_used` / `sse_connections` (all `Gauge`) and `messages_total` (`Counter`). Use `prometheus_client.REGISTRY` (default) for all.
- [x] 3.3 Implement `setup_metrics(session_registry, worker_registry, sse_registry, engine)` that binds `Gauge.set_function` callbacks to the registries and the engine pool. Callbacks must be safe to call from the metrics scrape thread (registries are already thread-safe dict accesses, confirm).
- [x] 3.4 Implement `metrics_endpoint()` returning `Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)`.
- [x] 3.5 Mount `/metrics` route in `src/main.py` at the root prefix (NOT under `/api`), after `/health` and before the `/api` router include. Ensure no auth dependency is attached.
- [x] 3.6 Wire `messages_total.inc()` into `src/event_bus/bus.py` (or equivalent) inside the `publish()` method, AFTER the subscribers dispatch succeeds (on exception path do NOT increment).
- [x] 3.7 Wire `sse_connections` gauge to whatever SSE handler registry exists (`src/api/sessions.py`, `src/api/runs.py`, `src/api/notify.py`) — if no central registry, add a simple `set[int]` of connection ids that handlers add/remove in a try/finally.
- [x] 3.8 Unit test `scripts/test_metrics.py`: (a) import the module, (b) call `setup_metrics` with fake registries, (c) register fake items, (d) call `generate_latest()`, (e) assert all 5 metric names are present and the gauge values match the fake registry state.
- [x] 3.9 Integration test: bring up the compose stack (core only, no monitoring profile), curl `http://localhost:8000/metrics` via `docker compose exec api curl`, assert 200 + all 5 metric names present. Add this as `scripts/test_metrics_http.py` (a short script, not part of the smoke test).

## 4. nginx SSE timeout location block

- [x] 4.1 Edit `web/nginx.conf`: add a new `location /api/sessions/` block BEFORE the existing `location /api/` block, with `proxy_read_timeout 3600s`, `proxy_send_timeout 3600s`, `proxy_buffering off`, `proxy_cache off`, and the standard proxy headers (copy from the existing `/api/` block). Add a `/metrics` location block proxying to `http://api:8000/metrics`.
- [x] 4.2 Manual verification: `docker compose up --build web`, open DevTools Network tab, start a `blog_with_review` pipeline, wait at the review interrupt for >90 seconds, confirm the SSE connection stays open (no "reconnecting..." indicator, ping comments continue to arrive)
- [x] 4.3 Update the `docker-compose-stack` `Nginx configuration` scenario list in the archived spec (after archive) — handled by sync, not a manual edit here

## 5. Monitoring compose profile

- [x] 5.1 Create `deploy/prometheus.yml` with a single scrape job `mas-pipeline` targeting `api:8000` at 15s intervals. Validate with `docker run --rm -v $(pwd)/deploy/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus:latest promtool check config /etc/prometheus/prometheus.yml`
- [x] 5.2 Create `deploy/grafana/provisioning/datasources/datasource.yml` provisioning a Prometheus data source pointing at `http://prometheus:9090` named `Prometheus`, with `isDefault: true`
- [x] 5.3 Create `deploy/grafana/provisioning/dashboards/dashboards.yml` pointing Grafana's file provider at `/var/lib/grafana/dashboards`
- [x] 5.4 Create `deploy/grafana/dashboards/mas-pipeline.json` with 5 panels (stat + timeseries layout for each metric). Start from a minimal hand-written JSON or export from a local Grafana after manual config; validate with `python -m json.tool`
- [x] 5.5 Add `prometheus` and `grafana` services to `docker-compose.yaml` under `profiles: [monitoring]`, wiring the bind-mounts, volumes, ports, and health dependencies from the spec
- [x] 5.6 Add `start_with_monitoring.sh` (optional convenience) or just document the flag in README — skip if README docs are sufficient
- [x] 5.7 Manual end-to-end: `docker compose --profile monitoring up`, navigate to `http://localhost:3000` (admin/admin), confirm data source exists, open "mas-pipeline" dashboard, trigger some API activity via the UI, confirm metrics move

## 6. Documentation

- [x] 6.1 Add a "Monitoring (optional)" section to `README.md` explaining: how to opt in (`docker compose --profile monitoring up`), default ports (9090, 3000), default Grafana login (admin/admin), location of the dashboard JSON, and how to add a new panel
- [x] 6.2 Add a one-liner to `README.md` near the top of the setup section noting "the API runs as a single worker by default — do not increase; see docs/deployment.md" (create `docs/deployment.md` if it does not exist, with one section explaining single-worker rationale and linking to `.plan/rest_api_deployment_risks.md`)
- [x] 6.3 Update `.env.example` to include `PROMETHEUS_PORT=9090`, `GRAFANA_PORT=3000`, `DATABASE_POOL_SIZE=20`, `DATABASE_MAX_OVERFLOW=40` as commented-out optional overrides

## 7. Verification

- [x] 7.1 Run the existing smoke test (`python scripts/test_e2e_smoke.py`) with the core stack and verify it still passes (monitoring profile not enabled)
- [x] 7.2 Run `scripts/test_metrics_http.py` against the running stack, confirm all 5 metric names are returned
- [x] 7.3 Manually bring up monitoring profile, generate traffic via smoke test, open Grafana dashboard, confirm gauges update
- [x] 7.4 Run `openspec validate add-phase8-deployment-hardening --strict` and fix any findings before archive
