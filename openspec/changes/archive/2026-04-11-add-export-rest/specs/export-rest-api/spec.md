## ADDED Requirements

### Requirement: GET /api/runs/{run_id}/export downloads the run's final output as markdown

The mas-pipeline REST API SHALL expose `GET /api/runs/{run_id}/export` returning the WorkflowRun's persisted `final_output` as a markdown file. The endpoint SHALL be registered under the same `/api` prefix as other Phase 6.1/6.3/6.4 routers and SHALL require a valid API key via the shared `require_api_key` dependency.

On success, the response SHALL have:
- Status: 200
- Body: the raw UTF-8 encoded bytes of `metadata_['final_output']` (no JSON wrapping)
- `Content-Type`: `text/markdown; charset=utf-8`
- `Content-Disposition`: an `attachment` header carrying the derived filename. Because pipeline names may contain non-ASCII characters, the header SHALL include **both** an ASCII fallback (`filename="..."`) and an RFC 6266-style extended form (`filename*=UTF-8''<percent-encoded>`) so legacy and modern browsers both receive the intended name.

#### Scenario: Successful markdown download

- **GIVEN** a completed WorkflowRun with `pipeline='blog_generation'` and `metadata_={'final_output': '# Report\n\nhello'}`
- **WHEN** the client sends `GET /api/runs/{run_id}/export` with a valid API key
- **THEN** the response SHALL have status 200 AND body equal to `b'# Report\n\nhello'` AND `Content-Type` equal to `text/markdown; charset=utf-8` AND `Content-Disposition` containing `attachment` and the filename `blog_generation_{run_id_short}.md`

#### Scenario: Non-ASCII pipeline name yields both header forms

- **GIVEN** a completed WorkflowRun with `pipeline='博客生成'` and a non-empty final_output
- **WHEN** the client sends `GET /api/runs/{run_id}/export` with a valid API key
- **THEN** the `Content-Disposition` header SHALL include both a `filename="..."` ASCII fallback (with non-ASCII characters replaced by `_`) and a `filename*=UTF-8''...` extended form (with the original name percent-encoded)

### Requirement: GET /api/runs/{run_id}/export returns 404 for unknown runs

When the `run_id` does not match any WorkflowRun, the endpoint SHALL return status 404 with JSON body `{"detail": "run not found"}`.

#### Scenario: Unknown run_id

- **WHEN** `GET /api/runs/nonexistent/export` is called
- **THEN** the response status SHALL be 404 AND the body SHALL be `{"detail": "run not found"}`

### Requirement: GET /api/runs/{run_id}/export returns 409 for runs not yet completed

When the run exists but its status is not `completed`, the endpoint SHALL return status 409. The JSON body SHALL include a detail field whose content identifies the current run status so the caller can display why the export is unavailable.

#### Scenario: Export of running run

- **GIVEN** a WorkflowRun with `status='running'`
- **WHEN** `GET /api/runs/{run_id}/export` is called
- **THEN** the response status SHALL be 409 AND `response.json()['detail']` SHALL contain the substring `'running'`

#### Scenario: Export of failed run

- **GIVEN** a WorkflowRun with `status='failed'`
- **WHEN** `GET /api/runs/{run_id}/export` is called
- **THEN** the response status SHALL be 409

### Requirement: GET /api/runs/{run_id}/export returns 404 for completed runs missing final_output

When the run is completed but `metadata_['final_output']` is missing, None, or empty string (including legacy runs created before the persistence layer), the endpoint SHALL return status 404. The JSON body SHALL use a detail message distinct from the unknown-run case so a UI can render a different error: `{"detail": "run completed but has no exportable output"}`.

#### Scenario: Completed run with empty metadata

- **GIVEN** a WorkflowRun with `status='completed'` and `metadata_={}`
- **WHEN** `GET /api/runs/{run_id}/export` is called
- **THEN** the response status SHALL be 404 AND `response.json()['detail']` SHALL equal `'run completed but has no exportable output'`

### Requirement: GET /api/runs/{run_id}/export rejects unauthenticated requests

The endpoint SHALL require the `X-API-Key` header when `settings.api_keys` is non-empty, returning 401 for missing or mismatched keys — identical to all other Phase 6.1/6.4 REST routes.

#### Scenario: Missing API key

- **GIVEN** `settings.api_keys = ['k']`
- **WHEN** `GET /api/runs/{run_id}/export` is called without an `X-API-Key` header
- **THEN** the response status SHALL be 401
