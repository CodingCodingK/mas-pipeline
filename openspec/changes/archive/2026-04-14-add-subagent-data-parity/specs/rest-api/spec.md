## ADDED Requirements

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
