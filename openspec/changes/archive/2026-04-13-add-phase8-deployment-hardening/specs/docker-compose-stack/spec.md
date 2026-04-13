## MODIFIED Requirements

### Requirement: Nginx configuration
The project SHALL have a `web/nginx.conf` that configures Nginx to:
1. Serve static files from `/usr/share/nginx/html` on port 80
2. Proxy `/api/` requests to `http://api:8000/api/` with appropriate headers (Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto)
3. Proxy `/health` requests to `http://api:8000/health`
4. Proxy `/metrics` requests to `http://api:8000/metrics` (unauthenticated root-prefix endpoint)
5. Fall back to `/index.html` for all other paths (SPA history mode via `try_files $uri $uri/ /index.html`)
6. Support SSE across all `/api/*` endpoints by setting `proxy_buffering off`, `proxy_cache off`, and passing through the `X-Accel-Buffering: no` header
7. Expose a dedicated `location /api/sessions/` block placed BEFORE the generic `location /api/` block with `proxy_read_timeout 3600s` and `proxy_send_timeout 3600s`, so review-interrupt SSE connections can park for up to an hour without nginx cutting the connection. All other `/api/*` endpoints SHALL continue to use the default `proxy_read_timeout 60s`.

#### Scenario: SPA page loads
- **WHEN** a browser requests `http://localhost/` or any SPA route like `/projects/1`
- **THEN** Nginx serves `index.html` and the React app renders

#### Scenario: API proxy
- **WHEN** the SPA makes a request to `/api/health`
- **THEN** Nginx proxies the request to `http://api:8000/api/health` and returns the response

#### Scenario: SSE streaming
- **WHEN** the SPA opens an SSE connection to `/api/runs/{id}/stream` or `/api/notify/stream`
- **THEN** Nginx proxies without buffering and the connection stays open for event streaming

#### Scenario: Review interrupt parks beyond 60 seconds
- **WHEN** the SPA holds an SSE connection to `/api/sessions/{id}/events` for longer than 60 seconds with no events
- **THEN** Nginx SHALL NOT cut the connection (because `/api/sessions/` has `proxy_read_timeout 3600s`)
- **AND** the SSE 15-second ping comment SHALL continue to flow through without being buffered

#### Scenario: Metrics endpoint reachable through nginx
- **WHEN** a scraper requests `http://localhost/metrics` (via nginx)
- **THEN** the request SHALL be proxied to `http://api:8000/metrics` and return the Prometheus text format

## ADDED Requirements

### Requirement: Opt-in monitoring compose profile

The `docker-compose.yaml` SHALL define two additional services, `prometheus` and `grafana`, both tagged with `profiles: [monitoring]` so they are NOT started by default. Users SHALL start them via `docker compose --profile monitoring up` (or equivalent script flag). Neither service SHALL be a dependency of the core `api` or `web` services — bringing monitoring down SHALL NOT affect core operation.

The `prometheus` service SHALL:
1. Use image `prom/prometheus:v2.x` (pin a recent stable tag)
2. Bind-mount `./deploy/prometheus.yml` into `/etc/prometheus/prometheus.yml:ro`
3. Expose port `9090` on the host (configurable via `PROMETHEUS_PORT`, default `9090`)
4. Persist time-series data in a named volume `prometheus_data`
5. Scrape `api:8000/metrics` at 15-second intervals

The `grafana` service SHALL:
1. Use image `grafana/grafana:10.x-oss` (pin a recent stable tag)
2. Bind-mount `./deploy/grafana/provisioning` into `/etc/grafana/provisioning:ro`
3. Bind-mount `./deploy/grafana/dashboards` into `/var/lib/grafana/dashboards:ro`
4. Expose port `3000` on the host (configurable via `GRAFANA_PORT`, default `3000`)
5. Persist user settings in a named volume `grafana_data`
6. Default admin credentials `admin`/`admin` with a forced password change disabled (`GF_AUTH_DISABLE_LOGIN_FORM=false`, `GF_SECURITY_ADMIN_PASSWORD=admin`)
7. Depend on `prometheus` with `condition: service_started`

#### Scenario: Default up excludes monitoring
- **WHEN** `docker compose up` is run without the monitoring profile
- **THEN** only `postgres`, `redis`, `api`, and `web` SHALL start
- **AND** no `prometheus` or `grafana` containers SHALL exist

#### Scenario: Monitoring profile starts metrics stack
- **WHEN** `docker compose --profile monitoring up` is run
- **THEN** `prometheus` and `grafana` containers SHALL start in addition to the core services
- **AND** `http://localhost:9090/-/ready` SHALL return `Prometheus is Ready.` within 30 seconds
- **AND** `http://localhost:3000/api/health` SHALL return `{"database":"ok"}` within 30 seconds

#### Scenario: Monitoring failure does not affect core
- **WHEN** the `prometheus` or `grafana` container crashes or is stopped
- **THEN** the `api` and `web` containers SHALL continue serving traffic normally

### Requirement: Prometheus scrape configuration

The project SHALL provide `deploy/prometheus.yml` with a single scrape job named `mas-pipeline` that targets `api:8000/metrics`. Scrape interval SHALL be 15 seconds. The file SHALL use the standard Prometheus config format and SHALL be directly loadable by `prom/prometheus`.

#### Scenario: Prometheus ingests metrics
- **WHEN** the monitoring profile is up and both `api` and `prometheus` have been running for 30 seconds
- **THEN** querying `http://localhost:9090/api/v1/query?query=sessions_active` SHALL return a JSON result with `status: "success"` and at least one data point

### Requirement: Grafana provisioning and default dashboard

The project SHALL provide `deploy/grafana/provisioning/datasources/datasource.yml` that provisions a Prometheus data source pointing at `http://prometheus:9090` at Grafana boot time. It SHALL also provide `deploy/grafana/provisioning/dashboards/dashboards.yml` (a dashboard provider config) and `deploy/grafana/dashboards/mas-pipeline.json` (the dashboard definition). The dashboard SHALL include five panels — one per metric (`sessions_active`, `workers_running`, `pg_connections_used`, `sse_connections`, `messages_total`) — each showing both the current value and a one-hour time series.

#### Scenario: Grafana opens to provisioned dashboard
- **WHEN** the monitoring profile is up and a user navigates to `http://localhost:3000/dashboards`
- **THEN** the dashboard named "mas-pipeline" SHALL appear in the list without manual import
- **AND** opening the dashboard SHALL show five panels populated with live data

#### Scenario: Grafana data source points at Prometheus
- **WHEN** the monitoring profile starts
- **THEN** Grafana's data source list SHALL contain one entry named `Prometheus` with URL `http://prometheus:9090` and type `prometheus`
