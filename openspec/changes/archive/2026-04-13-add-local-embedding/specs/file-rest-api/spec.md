## ADDED Requirements

### Requirement: File upload does not depend on embedding service availability

`POST /api/projects/{project_id}/files` SHALL succeed and persist the uploaded file and `Document` record regardless of embedding service availability. The upload path SHALL NOT call the embedder and SHALL NOT fail when the configured embedding endpoint is unreachable or misconfigured.

#### Scenario: Upload succeeds with embedding endpoint down
- **WHEN** a client POSTs a valid file and nothing is listening on `settings.embedding.api_base`
- **THEN** the response SHALL be 200 with the Document fields populated as usual
- **AND** the file SHALL be persisted under `uploads/{project_id}/{filename}`
- **AND** a row SHALL exist in `documents` for the file
- **AND** no request SHALL be made to the embedding endpoint during the upload call
