# rest-api Specification

## Purpose
TBD - created by archiving change add-rest-api-session-runner. Update Purpose after archive.
## Requirements
### Requirement: FastAPI app mounts versioned API router under `/api`
`src/main.py` SHALL include a FastAPI router (mounted at prefix `/api`) that aggregates the routers from `src/api/projects.py`, `src/api/sessions.py`, `src/api/runs.py`, and `src/api/auth.py`. All endpoints in this capability SHALL be exposed under the `/api` prefix.

#### Scenario: API router mounted
- **WHEN** the FastAPI app starts up
- **THEN** the routes returned by `app.routes` SHALL include the endpoints listed in this capability under prefix `/api`
- **AND** `GET /health` SHALL remain unchanged at the root prefix

### Requirement: API Key authentication via X-API-Key header
All `/api/*` endpoints (except `GET /health`) SHALL require a valid `X-API-Key` header. The list of valid keys SHALL be loaded from `settings.api_keys` at startup. Requests with missing or invalid keys SHALL receive HTTP 401 with body `{"detail": "invalid api key"}`.

#### Scenario: Valid API key
- **WHEN** a request includes header `X-API-Key: <key in settings.api_keys>`
- **THEN** the request SHALL pass authentication and proceed to the route handler

#### Scenario: Missing API key
- **WHEN** a request to `/api/projects` omits the `X-API-Key` header
- **THEN** the response SHALL be HTTP 401 with body `{"detail": "invalid api key"}`

#### Scenario: Invalid API key
- **WHEN** a request includes header `X-API-Key: not-a-real-key`
- **THEN** the response SHALL be HTTP 401 with body `{"detail": "invalid api key"}`

#### Scenario: Empty api_keys list disables auth
- **WHEN** `settings.api_keys` is an empty list
- **THEN** all requests SHALL pass authentication regardless of header (development mode)

### Requirement: Create chat session endpoint
`POST /api/projects/{project_id}/sessions` SHALL create a new `ChatSession` row with the requested `mode` and return the session id. Request body: `{"mode": "chat" | "autonomous", "channel": str = "web", "chat_id": str}`. The created session SHALL have `session_key = f"{channel}:{chat_id}"`, the requested mode, status `active`, and a freshly-created `Conversation` row linked via `conversation_id`.

#### Scenario: Create chat session
- **WHEN** `POST /api/projects/1/sessions` is called with body `{"mode": "chat", "channel": "web", "chat_id": "abc"}`
- **THEN** the response SHALL be HTTP 201 with body `{"id": <int>, "mode": "chat", "session_key": "web:abc", "conversation_id": <int>}`
- **AND** a `chat_sessions` row SHALL exist with `mode="chat"` and `project_id=1`

#### Scenario: Create autonomous session
- **WHEN** `POST /api/projects/1/sessions` is called with body `{"mode": "autonomous", "channel": "web", "chat_id": "xyz"}`
- **THEN** the created `chat_sessions` row SHALL have `mode="autonomous"`

#### Scenario: Invalid mode rejected
- **WHEN** `POST /api/projects/1/sessions` is called with body `{"mode": "invalid", "channel": "web", "chat_id": "x"}`
- **THEN** the response SHALL be HTTP 422 (validation error)

#### Scenario: Duplicate session_key returns existing
- **WHEN** `POST /api/projects/1/sessions` is called twice with the same `channel` and `chat_id`
- **THEN** the second call SHALL return the existing session id (idempotent)

### Requirement: Send message endpoint
`POST /api/sessions/{session_id}/messages` SHALL accept a user message, append it to the conversation, and ensure a SessionRunner is active for that session. The endpoint SHALL return immediately (HTTP 202) without waiting for the assistant turn to complete. Request body: `{"content": str | list[dict]}`.

#### Scenario: Send message to existing session
- **WHEN** `POST /api/sessions/1/messages` is called with `{"content": "hello"}`
- **THEN** the response SHALL be HTTP 202 with body `{"message_index": <int>}`
- **AND** the user message SHALL be appended to the corresponding `Conversation.messages`
- **AND** a SessionRunner for session 1 SHALL be active (created if not yet)

#### Scenario: Send message to nonexistent session
- **WHEN** `POST /api/sessions/999/messages` is called
- **THEN** the response SHALL be HTTP 404 with body `{"detail": "session not found"}`

#### Scenario: Multimodal content accepted
- **WHEN** `POST /api/sessions/1/messages` is called with `{"content": [{"type": "text", "text": "..."}, {"type": "image", "source": {...}}]}`
- **THEN** the message SHALL be appended as-is and the response SHALL be HTTP 202

### Requirement: SSE event subscription endpoint
`GET /api/sessions/{session_id}/events` SHALL return an SSE (`text/event-stream`) response that streams `StreamEvent` JSON objects emitted by the SessionRunner for that session. The endpoint SHALL honor the `Last-Event-ID` request header for backfill.

#### Scenario: Subscribe with no Last-Event-ID
- **WHEN** `GET /api/sessions/1/events` is called without `Last-Event-ID`
- **THEN** the response SHALL be `text/event-stream`
- **AND** events emitted by SessionRunner 1 from now on SHALL be streamed to the client

#### Scenario: Subscribe with Last-Event-ID for backfill
- **WHEN** `GET /api/sessions/1/events` is called with header `Last-Event-ID: 5`
- **THEN** the server SHALL first replay events corresponding to `Conversation.messages[6:]` (one event per message), then continue with live events

#### Scenario: SSE keepalive
- **WHEN** an SSE connection has been idle (no events) for ≥ 15 seconds
- **THEN** the server SHALL send a `: ping\n\n` comment line to prevent proxy idle timeout

#### Scenario: Slow client disconnected
- **WHEN** an SSE event push to a client takes longer than 5 seconds
- **THEN** the server SHALL close that client's connection and continue serving other subscribers without blocking the SessionRunner

### Requirement: Trigger named pipeline endpoint
`POST /api/projects/{project_id}/pipelines/{pipeline_name}/runs` SHALL create a new `WorkflowRun` for the specified pipeline (e.g. `blog`, `courseware-exam`) and start execution. Optional query parameter `stream=true` SHALL switch the response to SSE that streams the pipeline's `StreamEvent`s in real time. Request body: `{"input": dict}`.

#### Scenario: Trigger blog pipeline
- **WHEN** `POST /api/projects/1/pipelines/blog/runs` is called with `{"input": {"topic": "Redis"}}`
- **THEN** a `WorkflowRun` row SHALL be created with `pipeline="blog"`, `project_id=1`, `status="running"`
- **AND** the response SHALL be HTTP 202 with body `{"run_id": <str>}`

#### Scenario: Trigger pipeline with SSE streaming
- **WHEN** `POST /api/projects/1/pipelines/blog/runs?stream=true` is called
- **THEN** the response SHALL be `text/event-stream`
- **AND** all `StreamEvent`s emitted by the pipeline execution SHALL be streamed

#### Scenario: Unknown pipeline name
- **WHEN** `POST /api/projects/1/pipelines/nonexistent/runs` is called
- **THEN** the response SHALL be HTTP 404 with body `{"detail": "pipeline not found: nonexistent"}`

### Requirement: Resume pipeline run endpoint
`POST /api/runs/{run_id}/resume` SHALL resume a LangGraph pipeline that is paused at an interrupt. Request body: `{"value": Any}` — the value supplied by the human reviewer to satisfy the interrupt. This SHALL invoke the same underlying resume primitive used by `gateway-resume`.

#### Scenario: Resume paused run
- **WHEN** a pipeline run with id "run_42" is paused at an interrupt and `POST /api/runs/run_42/resume` is called with `{"value": "approved"}`
- **THEN** the LangGraph PostgresSaver checkpoint SHALL be loaded and execution SHALL continue with the supplied value
- **AND** the response SHALL be HTTP 202 with body `{"run_id": "run_42", "status": "resumed"}`

#### Scenario: Resume non-paused run rejected
- **WHEN** `POST /api/runs/run_42/resume` is called for a run that is not currently paused
- **THEN** the response SHALL be HTTP 409 with body `{"detail": "run is not paused"}`

#### Scenario: Resume nonexistent run
- **WHEN** `POST /api/runs/nope/resume` is called
- **THEN** the response SHALL be HTTP 404 with body `{"detail": "run not found"}`

### Requirement: Cancel run endpoint
`POST /api/runs/{run_id}/cancel` SHALL cancel any running `WorkflowRun` (chat session or pipeline). The endpoint SHALL set the run's `abort_signal`, mark its status as `cancelled`, and return HTTP 202.

#### Scenario: Cancel running pipeline
- **WHEN** `POST /api/runs/run_42/cancel` is called for a running pipeline
- **THEN** the run's `abort_signal` SHALL be set
- **AND** the `WorkflowRun.status` SHALL transition to `cancelled`
- **AND** the response SHALL be HTTP 202

#### Scenario: Cancel already-finished run is no-op
- **WHEN** `POST /api/runs/run_42/cancel` is called for a run with `status="completed"`
- **THEN** the response SHALL be HTTP 202 with no state change

### Requirement: Read-only query endpoints
The following GET endpoints SHALL return JSON for inspection:
- `GET /api/projects` — list all projects accessible to the API key
- `GET /api/projects/{id}` — single project detail
- `GET /api/sessions/{id}` — chat session detail (mode, status, conversation_id, created_at)
- `GET /api/sessions/{id}/messages?offset=&limit=` — paginated conversation history
- `GET /api/runs/{run_id}` — workflow run detail (status, pipeline, started_at, finished_at)

#### Scenario: List projects
- **WHEN** `GET /api/projects` is called
- **THEN** the response SHALL be HTTP 200 with body `{"items": [<project>...]}`

#### Scenario: Get session messages with pagination
- **WHEN** `GET /api/sessions/1/messages?offset=10&limit=20` is called
- **THEN** the response SHALL be HTTP 200 with body `{"items": [...], "total": <int>}` containing at most 20 messages

### Requirement: Error response format
All error responses SHALL use FastAPI's default `{"detail": <str>}` body and standard HTTP status codes (400 validation, 401 auth, 404 not found, 409 conflict, 500 internal).

#### Scenario: Validation error format
- **WHEN** a request with invalid JSON body is rejected
- **THEN** the response body SHALL contain a `detail` field describing the validation failure

### Requirement: Single-worker startup warning
On FastAPI startup, the application SHALL inspect the `WEB_CONCURRENCY` environment variable. If set and not equal to `"1"`, the application SHALL log a WARNING that multi-worker deployment is not yet supported by SessionRunner and may cause session state inconsistency.

#### Scenario: Multi-worker warning emitted
- **WHEN** the server starts with `WEB_CONCURRENCY=4`
- **THEN** a WARNING-level log SHALL be emitted referencing SessionRunner and sticky routing

#### Scenario: Single worker is silent
- **WHEN** the server starts with `WEB_CONCURRENCY=1` or unset
- **THEN** no warning SHALL be emitted

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

### Requirement: GET /api/agent-runs/{id} returns agent run details with transcript
The REST API SHALL expose `GET /api/agent-runs/{id}` that returns a JSON object containing the full AgentRun record including the `messages` JSONB transcript and the three statistics fields. This endpoint SHALL be used by frontend analysis pages (chat detail drawer, pipeline run detail drawer) for post-hoc inspection of sub-agent activity.

Response schema:
```json
{
  "id": 123,
  "run_id": 456,
  "role": "analyst",
  "description": "...",
  "status": "completed",
  "owner": "run-xxx:analyst",
  "result": "...",
  "messages": [...],
  "tool_use_count": 5,
  "total_tokens": 12453,
  "duration_ms": 47123,
  "created_at": "2026-04-14T...",
  "updated_at": "2026-04-14T..."
}
```

The endpoint SHALL return HTTP 404 with `{"detail": "agent run not found"}` when the id does not exist. It SHALL be subject to the same X-API-Key auth as other `/api/*` routes.

#### Scenario: Fetch existing agent run
- **WHEN** `GET /api/agent-runs/123` is called for an existing completed run
- **THEN** the response SHALL be HTTP 200 with all fields populated, including `messages` as a JSON array

#### Scenario: Fetch non-existent agent run
- **WHEN** `GET /api/agent-runs/99999` is called for an id that doesn't exist
- **THEN** the response SHALL be HTTP 404 with body `{"detail": "agent run not found"}`

#### Scenario: List endpoint excludes messages for performance
- **WHEN** the existing list endpoint `GET /api/runs/{run_id}/agent-runs` is called
- **THEN** the response SHALL NOT include the `messages` field (to avoid TOASTed column reads for list views)
- **AND** it SHALL continue to return the other compact fields (id, role, status, result, etc.)

#### Scenario: Auth enforced
- **WHEN** `GET /api/agent-runs/123` is called without an X-API-Key header and auth is enabled
- **THEN** the response SHALL be HTTP 401 (or the same code other /api/ routes return)

