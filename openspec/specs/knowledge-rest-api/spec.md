# knowledge-rest-api Specification

## Purpose
TBD - created by archiving change add-files-knowledge-rest. Update Purpose after archive.
## Requirements
### Requirement: Ingest endpoint creates a Job and runs ingest in background
`POST /api/projects/{project_id}/files/{file_id}/ingest` SHALL validate that the file belongs to the project, create a `Job(kind="ingest")` via `JobRegistry`, schedule `ingest_document(project_id, file_id, progress_callback=job.emit)` as an `asyncio` background task, and return `202 {job_id}` immediately without waiting for ingestion to complete.

#### Scenario: Ingest accepted
- **WHEN** a client POSTs ingest for an existing file
- **THEN** the response SHALL be 202 with `{job_id}`
- **AND** a Job SHALL exist in the registry with `status="running"`
- **AND** ingestion SHALL proceed in the background and emit progress events to the job's queue

#### Scenario: File not found
- **WHEN** the file_id does not belong to the project
- **THEN** the response SHALL be 404 and no Job SHALL be created

#### Scenario: Ingest failure recorded on Job
- **WHEN** the embedding API raises during background ingestion
- **THEN** the Job SHALL transition to `status="failed"` with `error` populated
- **AND** the Job's queue SHALL receive a `{"event": "failed", "error": ...}` event followed by sentinel close

### Requirement: Chunks endpoint returns paginated chunk previews
`GET /api/projects/{project_id}/files/{file_id}/chunks?offset=0&limit=20` SHALL return chunks for the document ordered by `chunk_index` ascending, sliced by offset and limit. The endpoint SHALL enforce `0 <= offset` and `1 <= limit <= 100`.

#### Scenario: Default pagination
- **WHEN** a client requests chunks without query params
- **THEN** the response SHALL contain at most 20 chunks ordered by chunk_index
- **AND** the response shape SHALL be `{items: [{chunk_index, content, metadata}], total, offset, limit}`

#### Scenario: Custom pagination
- **WHEN** a client requests `?offset=20&limit=10`
- **THEN** the response SHALL contain chunks 20–29

#### Scenario: Limit exceeds maximum
- **WHEN** a client requests `?limit=200`
- **THEN** the response SHALL be 422 (validation error)

#### Scenario: Document with no chunks
- **WHEN** the document has not yet been ingested
- **THEN** the response SHALL be 200 with `{items: [], total: 0, offset: 0, limit: 20}`

### Requirement: Knowledge status endpoint returns project aggregates
`GET /api/projects/{project_id}/knowledge/status` SHALL return `{file_count, parsed_count, total_chunks}` aggregated across all documents in the project.

#### Scenario: Status reflects ingestion state
- **WHEN** a project has 3 files and 1 has been ingested with 50 chunks
- **THEN** the response SHALL be `{file_count: 3, parsed_count: 1, total_chunks: 50}`

