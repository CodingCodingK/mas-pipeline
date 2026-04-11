## ADDED Requirements

### Requirement: JobRegistry manages in-memory long-task lifecycle
The system SHALL provide a `JobRegistry` class in `src/jobs/registry.py` exposing `create(kind) -> Job`, `get(job_id) -> Job | None`, `list() -> list[Job]`, and `async cleanup_finished(max_age_sec) -> int`. A module-level singleton SHALL be accessible via `get_registry()`.

#### Scenario: Create returns a new pending Job
- **WHEN** `registry.create(kind="ingest")` is called
- **THEN** a Job SHALL be returned with `status="pending"`, a unique `id`, `started_at` set to now, and an empty `asyncio.Queue` of maxsize 1000

#### Scenario: Get returns the same instance
- **WHEN** `registry.create()` returns a Job and `registry.get(job.id)` is called
- **THEN** the same Job instance SHALL be returned

#### Scenario: cleanup_finished removes old finished jobs
- **WHEN** the registry contains 1 running job, 1 done job finished 1 hour ago, and 1 done job finished 2 days ago
- **AND** `cleanup_finished(max_age_sec=86400)` is called
- **THEN** only the 2-day-old job SHALL be removed and the function SHALL return 1
- **AND** the running job and 1-hour-old job SHALL remain

#### Scenario: get_registry returns a singleton
- **WHEN** `get_registry()` is called twice
- **THEN** the same `JobRegistry` instance SHALL be returned

### Requirement: Job emits progress events through a bounded queue
`Job.emit(event: dict)` SHALL `put_nowait` the event into the job's queue. On a full queue, the oldest event SHALL be dropped to make room (drop-oldest). The Job SHALL also store the event as `last_event`. When `event["event"]` is `"done"` or `"failed"`, the Job SHALL set `status` accordingly, set `finished_at` to now, set `error` from `event.get("error")` if failed, and put a `None` sentinel into the queue to signal stream end.

#### Scenario: Emit running event
- **WHEN** a freshly created Job receives `emit({"event": "parsing_started"})`
- **THEN** `status` SHALL transition to `"running"` (from `"pending"`)
- **AND** `last_event` SHALL equal the emitted dict
- **AND** the queue SHALL contain the event

#### Scenario: Emit done sentinel
- **WHEN** a Job receives `emit({"event": "done", "chunks": 42})`
- **THEN** `status` SHALL be `"done"`
- **AND** `finished_at` SHALL be set
- **AND** the queue SHALL contain the event followed by `None`

#### Scenario: Emit failed sets error
- **WHEN** a Job receives `emit({"event": "failed", "error": "API timeout"})`
- **THEN** `status` SHALL be `"failed"`, `error` SHALL be `"API timeout"`, `finished_at` SHALL be set
- **AND** the queue SHALL contain the event followed by `None`

#### Scenario: Drop-oldest on overflow
- **WHEN** a Job's queue is full (1000 events) and `emit` is called
- **THEN** the oldest event SHALL be dropped and the new event SHALL be enqueued
- **AND** no exception SHALL be raised

### Requirement: Job query endpoint returns metadata
`GET /api/jobs/{job_id}` SHALL return `Job.to_dict()` (excluding the queue). The endpoint SHALL return 404 if the job does not exist.

#### Scenario: Existing job
- **WHEN** a client GETs `/api/jobs/{id}` for a Job in `running` state
- **THEN** the response SHALL contain `{id, kind, status, error: null, started_at, finished_at: null, last_event}`

#### Scenario: Missing job
- **WHEN** a client GETs `/api/jobs/{nonexistent_id}`
- **THEN** the response SHALL be 404

### Requirement: Job SSE stream emits progress until completion
`GET /api/jobs/{job_id}/stream` SHALL open a Server-Sent Events stream that yields each event from the Job's queue as `event: progress\ndata: <json>\n\n` frames until the sentinel `None` is received. The endpoint SHALL send a heartbeat comment line every 30 seconds when the queue is idle. On client disconnect, the endpoint SHALL exit cleanly without raising.

#### Scenario: Stream live progress
- **WHEN** a Job receives 5 progress events followed by `done` sentinel
- **THEN** the SSE client SHALL receive 5 `event: progress` frames + 1 `event: progress` for the done event in order, then the stream SHALL close

#### Scenario: Stream a finished job
- **WHEN** a client opens the stream for a Job whose status is already `done`
- **THEN** the SSE response SHALL emit `last_event` as a single `event: progress` frame and immediately close

#### Scenario: Stream non-existent job
- **WHEN** a client opens `/api/jobs/{nonexistent}/stream`
- **THEN** the response SHALL be 404

#### Scenario: Heartbeat on idle queue
- **WHEN** the queue has no events for more than 30 seconds
- **THEN** the SSE response SHALL emit a comment line `: keepalive\n\n` and continue waiting

### Requirement: Cleanup loop runs in lifespan
`src/main.py` lifespan SHALL start a background task running `start_cleanup_loop(registry, interval_sec=3600)` after the registry is initialized and SHALL cancel it on shutdown.

#### Scenario: Cleanup loop cancellation on shutdown
- **WHEN** the FastAPI app shuts down
- **THEN** the cleanup loop background task SHALL be cancelled and awaited
