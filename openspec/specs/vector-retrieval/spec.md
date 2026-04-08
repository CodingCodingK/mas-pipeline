## ADDED Requirements

### Requirement: retrieve returns relevant chunks by vector similarity
`retrieve(project_id, query, top_k=5)` SHALL embed the query, then find the most similar document_chunks using pgvector cosine distance, filtered by project_id.

#### Scenario: Successful retrieval
- **WHEN** retrieve is called with a project that has indexed documents
- **THEN** it SHALL return up to top_k `RetrievalResult` objects ordered by similarity (most similar first)

#### Scenario: Project isolation
- **WHEN** retrieve is called for project_id=1
- **THEN** results SHALL only contain chunks from documents belonging to project_id=1

#### Scenario: No matching documents
- **WHEN** retrieve is called for a project with no indexed chunks
- **THEN** it SHALL return an empty list

### Requirement: RetrievalResult contains content and metadata
`RetrievalResult` SHALL be a dataclass with `content` (str), `metadata` (dict), `score` (float), and `doc_id` (int).

#### Scenario: Result fields
- **WHEN** a RetrievalResult is returned
- **THEN** it SHALL have content (chunk text), metadata (from document_chunks.metadata), score (cosine similarity), and doc_id (source document ID)

### Requirement: ingest_document orchestrates the full pipeline
`ingest_document(project_id, doc_id)` SHALL parse the document, chunk the text, embed all chunks, store them in document_chunks, and update the Document record.

#### Scenario: Successful ingest
- **WHEN** ingest_document is called for a valid document
- **THEN** it SHALL parse → chunk → embed → INSERT chunks into document_chunks → UPDATE Document.parsed=True and Document.chunk_count=N

#### Scenario: Document not found
- **WHEN** ingest_document is called with a non-existent doc_id
- **THEN** it SHALL raise ValueError

#### Scenario: Re-ingest replaces old chunks
- **WHEN** ingest_document is called for an already-ingested document
- **THEN** it SHALL DELETE existing chunks for that doc_id before inserting new ones
