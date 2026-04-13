# Deployment Notes

## Single-worker constraint

`mas-pipeline` runs as a **single uvicorn worker**. Setting `WEB_CONCURRENCY>1` or `UVICORN_WORKERS>1` causes the API to log CRITICAL and exit at startup.

**Why**: `SessionRunner` holds in-process state — an asyncio task per active session plus its bus subscribers and SSE queues. In a multi-worker deployment, two requests for the same session can land on different worker processes, each spawning its own runner. The result is divergent state, duplicate events, and lost messages. Sticky session routing (nginx / PG advisory locks) would solve it but is not implemented.

**Impact**: a single worker handles all traffic for this instance. On modern hardware this is enough for dozens of concurrent sessions — the LLM call is almost always the bottleneck, not Python CPU time. Horizontal scaling requires running multiple *instances* behind a load balancer with session affinity (stick on session_id), which is a project-level decision beyond the API.

See `.plan/rest_api_deployment_risks.md` risk #1 for the full rationale and future-upgrade options.

## Database connection pool

Default SQLAlchemy pool: `pool_size=20`, `max_overflow=40` (so up to 60 concurrent connections from the API). Override via env: `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW`. Keep `pool_size + max_overflow ≤ PG max_connections - 10` to leave headroom for `psql`/admin sessions — the API logs a WARNING at startup if this invariant is violated.

## SSE through nginx

`web/nginx.conf` sets `proxy_buffering off`, `proxy_cache off`, and `proxy_read_timeout 3600s` on `/api/`. This lets review-interrupt SSE connections park for up to an hour while the user decides. If you swap out nginx, preserve these three settings.

## Monitoring

See the "Monitoring (optional)" section in `README.md` for the opt-in Prometheus + Grafana stack.
