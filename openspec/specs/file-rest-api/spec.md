# file-rest-api Specification

## Purpose
TBD - created by archiving change add-files-knowledge-rest. Update Purpose after archive.
## Requirements
### Requirement: File upload endpoint accepts multipart and registers a Document
The system SHALL provide `POST /api/projects/{project_id}/files` accepting `multipart/form-data` with a single file part. The endpoint SHALL save the upload to a temporary path, call `files.manager.upload(project_id, temp_path)`, and return the resulting Document as JSON.

#### Scenario: Valid upload returns 200 with Document fields
- **WHEN** a client POSTs a `.md` file with valid `X-API-Key`
- **THEN** the response SHALL be 200 with `{id, filename, file_type, file_size, parsed: false, chunk_count: 0, created_at}`
- **AND** the file SHALL be persisted under `uploads/{project_id}/{filename}`
- **AND** a row SHALL exist in `documents` for the file

#### Scenario: Disallowed extension returns 400
- **WHEN** a client uploads a `.exe` file
- **THEN** the response SHALL be 400 with an error message indicating the file type is not supported

#### Scenario: Missing API key returns 401
- **WHEN** a client POSTs without `X-API-Key`
- **THEN** the response SHALL be 401

### Requirement: List files endpoint returns project documents newest first
`GET /api/projects/{project_id}/files` SHALL return a JSON array of Documents belonging to the project, ordered by `created_at` descending.

#### Scenario: Project with files
- **WHEN** the project has 3 uploaded documents
- **THEN** the response SHALL be 200 with a 3-element array ordered newest-first

#### Scenario: Empty project
- **WHEN** the project has no documents
- **THEN** the response SHALL be 200 with `[]`

### Requirement: Delete file endpoint removes record and physical file
`DELETE /api/projects/{project_id}/files/{file_id}` SHALL delete the documents row (cascading chunk deletion) and remove the physical file. The endpoint SHALL return 204 on success and 404 if the file does not belong to the project.

#### Scenario: Successful delete
- **WHEN** a client deletes an existing file
- **THEN** the response SHALL be 204
- **AND** the documents row SHALL be removed
- **AND** the physical file SHALL no longer exist on disk

#### Scenario: Deleting non-existent file
- **WHEN** a client deletes a file_id that does not exist for the project
- **THEN** the response SHALL be 404

#### Scenario: Cross-project isolation
- **WHEN** project A tries to delete a file belonging to project B
- **THEN** the response SHALL be 404 (project B's file is not modified)

