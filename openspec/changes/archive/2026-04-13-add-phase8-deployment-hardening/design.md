## Context

Phase 6.1 built SessionRunner on the assumption of a single API worker; Phase 7 shipped the docker-compose stack and an end-to-end smoke test confirming the happy path works. But `.plan/rest_api_deployment_risks.md` flagged six deployment-side risks that were deliberately left for a later phase. Three of them — undersized PG pool, nginx idle-kill on SSE review interrupts, and zero operational visibility — are blockers for anyone running this on a real server and cannot be deferred to "Phase 9" because there is no Phase 9. This change closes those three and documents why the other three (multi-worker routing, index tuning, cross-restart worker recovery) stay deferred.

Current state (pre-change):
- `src/db.py` creates the SQLAlchemy engine with `create_engine(url)` — no pool args, so SQLAlchemy defaults (`pool_size=5, max_overflow=10`, `pool_pre_ping=False`) apply. With 1 SessionRunner per active conversation each holding a short-lived DB session at burst points, 15 concurrent users can already hit the cliff.
- `web/nginx.conf` has a single `location /api/` block with `proxy_buffering off` but the default `proxy_read_timeout 60s`. SSE ping is emitted every 15s so streaming pipelines work fine — but review interrupts (`blog_with_review`) park with no events until the user clicks approve, and the ping interval does not count as "real" proxy activity against some nginx configurations. More importantly, if anyone bumps the ping interval later or the review sits behind a slow user (lunch break), 60s is not enough.
- There is no `/metrics` endpoint. Debugging a stuck system means SSH + `docker compose logs -f`. No time series, no correlation, no alerts.

The one non-obvious constraint: risk #1 (multi-worker session routing) is NOT being solved here. Instead this change hardens the "single worker" assumption with a startup check that loudly warns if someone tries `--workers 2+`, so the trap is visible rather than silent.

## Goals / Non-Goals

**Goals:**
- PG pool sized for realistic concurrency, tunable via settings, with a startup sanity check against PG `max_connections`.
- nginx config that lets a review interrupt park for up to an hour without being cut.
- `/metrics` endpoint exposing the 5 core operational gauges/counters defined in the spec, zero-cost when nobody scrapes it.
- Prometheus + Grafana compose services gated behind an opt-in profile so the default stack stays minimal.
- Grafana opens to a pre-provisioned dashboard showing the 5 metrics — zero manual setup.
- Hard single-worker invariant enforced at startup (if env tries to override, log loud warning).

**Non-Goals:**
- Multi-worker session routing / sticky load balancing / PG advisory locks (risk #1 — stays deferred, single-worker is the contract).
- PG index optimization (risk #3 — no evidence of bottleneck, not doing pre-optimization).
- Cross-restart recovery of in-flight agent workers (risk #5 — known limitation, short workers make it acceptable).
- Business metrics: per-pipeline counts, per-agent call histograms, per-user activity. If someone needs these later, build a separate `/api/stats` endpoint against PG — do not pollute `/metrics`.
- Authentication on `/metrics`. Prometheus scrapes come from inside the compose network; if the endpoint is ever exposed externally, bind it to localhost via a separate setting.
- Alerting rules. Dashboard only. Alerts require a receiver (email/slack/webhook) and policy decisions that are out of scope.
- Log aggregation / distributed tracing (Loki, Tempo, Jaeger). Explicitly excluded — this change does metrics only.

## Decisions

### 1. Use `prometheus-client` (official Python library) over DIY text generation

**Decision**: Add `prometheus-client` to `requirements.txt`, use its `Gauge` / `Counter` primitives and `generate_latest()` + `CONTENT_TYPE_LATEST` for the endpoint.

**Alternatives considered**:
- Hand-write the Prometheus text format. 20 lines, zero deps. Rejected because: (a) label escaping rules are a footgun, (b) the library handles histogram bucket boundaries, exemplars, and the `# HELP`/`# TYPE` preamble correctly, (c) the library is 50KB, single-file, and has no transitive deps of note.
- OpenTelemetry metrics SDK. Rejected because: the value proposition (vendor neutrality, traces + metrics + logs unification) is irrelevant at this stage, and it adds ~30 deps.

**Rationale**: The library is the de-facto standard, already what FastAPI examples use, and keeps us compatible with any Prometheus-compatible scraper (Nightingale, VictoriaMetrics, Grafana Agent).

### 2. Gauges are pulled from registries via callbacks, not pushed from code paths

**Decision**: For gauges that reflect "current state" (`sessions_active`, `workers_running`, `pg_connections_used`, `sse_connections`), use `Gauge(...).set_function(lambda: registry.count())`. No code path needs to call `.inc()` or `.dec()`; the value is computed fresh on each scrape.

**Alternatives considered**:
- Increment/decrement on every lifecycle event (SessionRunner start → inc, stop → dec). Rejected because: (a) easy to drift (a crash between start and the inc/dec call desynchronizes), (b) SessionRunner and worker registry already own the source of truth, (c) scrapes are every 15s — computing a `len()` on a dict is free.

**Rationale**: Registries are already the source of truth. Don't duplicate state. The callback pattern gives us zero-drift-by-construction.

**Exception**: `messages_total` is a counter that accumulates over time and cannot be derived from state, so it uses `.inc()` at the bus publish site.

### 3. Prometheus + Grafana behind an opt-in compose profile

**Decision**: Add `profiles: [monitoring]` to both new services. Default `docker compose up` does NOT start them. Users opt in via `docker compose --profile monitoring up` or `./start.sh --monitoring`.

**Alternatives considered**:
- Always start them. Rejected because: (a) adds ~200MB of images + ~100MB RAM idle, (b) grafana opens port 3000 which may collide with dev setups, (c) most users (single-user dev mode) do not need monitoring and the extra noise hurts first-run experience.
- Separate `docker-compose.monitoring.yaml` override file. Rejected because compose profiles are the first-party way to gate services — override files are for environment differences, not opt-in features.

**Rationale**: Profiles are precisely the feature compose added for optional service groups. First-run experience stays clean; opting in is one flag.

### 4. Grafana dashboard is pre-provisioned via filesystem, not API-imported

**Decision**: Ship `deploy/grafana/provisioning/datasources/datasource.yml` (points at `http://prometheus:9090`) and `deploy/grafana/provisioning/dashboards/dashboards.yml` (scans `/var/lib/grafana/dashboards/`). Bind-mount `deploy/grafana/dashboards/mas-pipeline.json` into that scan directory. Grafana picks it up at boot.

**Alternatives considered**:
- Use Grafana's HTTP API after startup with a wait-and-POST script. Rejected because: timing-dependent, adds a script to maintain, provisioning-via-filesystem is the documented path.
- No provisioning — user imports dashboard JSON manually. Rejected because: "open Grafana, see dashboard" is the whole point; any manual step breaks the promise.

**Rationale**: Filesystem provisioning is idempotent, survives restarts, is in source control, and works offline.

### 5. PG pool size defaults and sanity check

**Decision**: Default `pool_size=20, max_overflow=40, pool_pre_ping=True`, loaded from `settings.database.*`. At engine construction time, if the computed effective pool (`pool_size + max_overflow`) exceeds a conservative threshold (e.g. `max_connections - 10` retrieved via `SHOW max_connections`), log a WARNING. Do NOT hard-fail — the check runs after engine creation and PG may legitimately have many connections reserved for other purposes.

**Alternatives considered**:
- No check, just set the defaults. Rejected because: silent oversubscription leads to `FATAL: too many connections` errors that look like application bugs.
- Hard-fail on oversubscription. Rejected because: PG `max_connections` defaults to 100 on most distros; `pool_size=20 + max_overflow=40 = 60` on a single API worker is fine, but adding any other connection consumer (psql debug sessions, a second app) could push over. Hard-failing the API for an ops-level config issue is too aggressive.

**Rationale**: Sensible defaults for realistic single-worker deployment + loud warning = ops-visible without being brittle.

### 6. Single-worker invariant enforced via startup check, not compose rewrite

**Decision**: `src/api/app.py` reads `WORKER_COUNT` at startup (from env, default 1). If > 1, log a CRITICAL error and `sys.exit(1)`. This catches operators who copy-paste `--workers 4` from tutorials.

**Alternatives considered**:
- Trust the CMD in Dockerfile. Rejected because the Dockerfile CMD can be overridden by `docker run` / compose `command:` and there is no compile-time check. A runtime assertion makes the contract visible where it is enforced.
- Support multi-worker via PG advisory locks. Rejected: out of scope, substantial design work (see `deployment_risks_session_runner.md`).

**Rationale**: The single-worker constraint is the load-bearing assumption of SessionRunner. Make it impossible to ignore.

### 7. nginx location block targets `/api/sessions/` specifically, not all of `/api/`

**Decision**: Add a new `location /api/sessions/` block BEFORE the existing `location /api/` block with `proxy_read_timeout 3600s`. All other `/api/*` endpoints keep the default 60s (which is fine for normal REST).

**Alternatives considered**:
- Bump `proxy_read_timeout 3600s` on the whole `/api/`. Rejected because: (a) it masks bugs in other endpoints that should respond quickly, (b) location specificity is the idiomatic nginx way.
- Target `/api/sessions/*/events` specifically. Rejected because: the prefix `/api/sessions/` covers both the SSE event endpoint and any related long-lived endpoints we may add later, and nginx longest-prefix matching already routes correctly.

**Rationale**: Scoped override, easy to reason about, extensible for future long-poll endpoints.

### 8. `/metrics` is unauthenticated

**Decision**: The `/metrics` endpoint SHALL bypass `X-API-Key` auth. It is a new route registered directly on the FastAPI app, not inside `/api`.

**Alternatives considered**:
- Require `X-API-Key`. Rejected because: (a) Prometheus scrape config cannot send custom auth headers without extra config and (b) the metrics themselves contain no sensitive data (counts, not content).
- Require a separate `X-Metrics-Key`. Rejected as premature — nothing in the compose network reaches `/metrics` except Prometheus itself.

**Rationale**: Low sensitivity, inside-network-only by default. If the operator exposes `/metrics` externally they can add auth at the nginx layer or switch to a `localhost`-bind variant later.

## Risks / Trade-offs

- **[Risk] Prometheus scrape adds latency spikes to /metrics under high gauge counts.** → Mitigation: only 5 metrics with O(1) `len()` callbacks, worst case sub-millisecond. Measure with smoke test.
- **[Risk] Grafana provisioning fails silently if JSON is malformed.** → Mitigation: validate JSON with `python -m json.tool` in tasks.md before shipping; Grafana logs the failure on boot which the smoke test can grep.
- **[Risk] PG pool_pre_ping adds a SELECT 1 roundtrip per checkout.** → Accepted: the cost (~0.3ms local) is worth the defense against stale connections after a PG restart, which is a real failure mode observed in dev.
- **[Risk] monitoring profile creates config drift vs Phase 7 smoke test stack.** → Mitigation: smoke test does NOT opt into the monitoring profile; it runs against the default stack, so monitoring services have no effect on smoke coverage. Add a separate `scripts/test_metrics.py` that curls `/metrics` against the running API and asserts all 5 metric names are present — covers the metrics pathway without pulling the whole monitoring stack into smoke.
- **[Risk] `worker_count > 1` startup check may trip in unusual dev setups (hot-reload workers, reload-on-change tools).** → Mitigation: the check looks at `UVICORN_WORKERS` env / `--workers` CLI arg, not internal reload mechanisms. Uvicorn's `--reload` does not set `--workers`.
- **[Trade-off] Opt-in monitoring profile means first-time users won't see the dashboard unless they know to flip the flag.** → Accepted: README documents it; default UX stays lean. Better than pushing 200MB+ of images on every dev machine that never looks at metrics.

## Migration Plan

1. **Database config (new settings block)**: add `database.pool_size`, `database.max_overflow`, `database.pool_pre_ping` to `config/settings.yaml` with defaults matching the decisions above. Existing deployments that do not set these pick up the new defaults automatically on restart. No migration script needed — pool sizing is runtime-only, no persistent state.
2. **nginx update**: edit `web/nginx.conf`. On redeploy, `docker compose up --build web` picks up the new config.
3. **/metrics endpoint**: new code, no migration. Existing clients unaffected.
4. **Monitoring services**: opt-in via profile. No impact on existing deployments unless explicitly enabled.
5. **Rollback**: revert the commit. `database.*` settings fall back to pre-change defaults via env override; nginx config reverts on next `docker compose up --build web`; /metrics 404s again; monitoring profile services were never required to be up.

## Open Questions

None at design time. All decisions confirmed with the user during discussion:
- User confirmed single-worker is the permanent constraint.
- User confirmed Prometheus + Grafana as the monitoring stack (vs Nightingale / dashboard alternatives).
- User confirmed running monitoring stack in-compose rather than as an external service.
- User confirmed the 5-metric minimum set is sufficient; business metrics explicitly excluded.
