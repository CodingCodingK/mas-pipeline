## ADDED Requirements

### Requirement: Ingest job surfaces embedding failures as structured errors

When background ingestion fails because the embedder raises an `EmbeddingError` subclass, the Job SHALL transition to `status="failed"` with `error` populated by a structured payload containing `{error_class, reason, api_base}`. The Job's event queue SHALL receive a `{"event": "failed", "error": {...}}` event before the sentinel close. The HTTP 202 response from `POST /api/projects/{project_id}/files/{file_id}/ingest` SHALL remain unchanged (the failure is observed via the Job, not the initial response).

#### Scenario: Ingest fails because embedding endpoint is unreachable
- **WHEN** a client POSTs ingest for an existing file and the embedder raises `EmbeddingUnreachableError`
- **THEN** the endpoint SHALL still return 202 with `{job_id}`
- **AND** the Job SHALL transition to `status="failed"` with `error.error_class == "EmbeddingUnreachableError"`, `error.reason` populated, and `error.api_base` equal to the configured embedding base URL

#### Scenario: Ingest fails on dimension mismatch
- **WHEN** background ingestion raises `EmbeddingDimensionMismatchError`
- **THEN** the Job's `error` payload SHALL include the configured dimension, the observed dimension, and the remediation command `python scripts/migrate_embedding_dim.py`
