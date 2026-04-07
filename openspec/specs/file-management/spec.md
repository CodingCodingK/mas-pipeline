## ADDED Requirements

### Requirement: upload registers a file and copies it to uploads directory
`upload(project_id, file_path)` SHALL validate the file extension, copy the file to `uploads/{project_id}/`, insert a row into the `documents` table, and return a Document instance.

#### Scenario: Valid file upload
- **WHEN** upload is called with a valid pdf/pptx/md/docx/png/jpg/jpeg file
- **THEN** the file SHALL be copied to `uploads/{project_id}/{filename}`, a documents row SHALL be inserted with correct project_id, filename, file_type, file_path, and file_size, and a Document instance SHALL be returned

#### Scenario: Invalid file type
- **WHEN** upload is called with a file extension not in the allowed list
- **THEN** it SHALL raise a ValueError indicating the file type is not supported

#### Scenario: Upload sets initial parsing state
- **WHEN** a file is uploaded
- **THEN** the document SHALL have parsed=False and chunk_count=0

### Requirement: list_files returns documents for a project
`list_files(project_id)` SHALL return all documents for the given project, ordered by created_at descending.

#### Scenario: Project has documents
- **WHEN** list_files is called for a project with uploaded documents
- **THEN** it SHALL return all documents ordered by created_at descending

#### Scenario: Project has no documents
- **WHEN** list_files is called for a project with no documents
- **THEN** it SHALL return an empty list

### Requirement: delete_file removes document record and physical file
`delete_file(project_id, doc_id)` SHALL delete the documents row (triggering CASCADE delete of chunks) and remove the physical file.

#### Scenario: Successful deletion
- **WHEN** delete_file is called for an existing document
- **THEN** the documents row SHALL be deleted, associated chunks SHALL be cascade-deleted, and the physical file SHALL be removed

#### Scenario: Physical file already missing
- **WHEN** delete_file is called but the physical file does not exist on disk
- **THEN** the documents row SHALL still be deleted without error

#### Scenario: Document not found
- **WHEN** delete_file is called with a non-existent doc_id
- **THEN** it SHALL return None

### Requirement: get_file_path returns the physical path of a document
`get_file_path(project_id, doc_id)` SHALL return the file path string for the given document.

#### Scenario: Document exists
- **WHEN** get_file_path is called for an existing document
- **THEN** it SHALL return the file_path stored in the documents row

#### Scenario: Document not found
- **WHEN** get_file_path is called for a non-existent document
- **THEN** it SHALL return None
