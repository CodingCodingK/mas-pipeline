## ADDED Requirements

### Requirement: search_docs degrades silently when embedding is unavailable

When the embedder raises any `EmbeddingError` subclass, `search_docs` SHALL catch it and return `ToolResult(output="RAG unavailable: no results", success=True)` so that the calling agent can continue. It SHALL NOT propagate the exception, SHALL NOT mark the tool call as failed, and SHALL NOT crash the agent run.

#### Scenario: Embedding endpoint unreachable
- **WHEN** an agent calls `search_docs` and the embedder raises `EmbeddingUnreachableError`
- **THEN** the tool SHALL return `ToolResult(output="RAG unavailable: no results", success=True)` and the agent run SHALL continue

#### Scenario: Embedding auth failure
- **WHEN** an agent calls `search_docs` and the embedder raises `EmbeddingAuthError`
- **THEN** the tool SHALL return a `success=True` result with a message indicating RAG is unavailable, and SHALL log the underlying error at WARNING level exactly once per process per error class

#### Scenario: Embedding dimension mismatch
- **WHEN** an agent calls `search_docs` and the embedder raises `EmbeddingDimensionMismatchError`
- **THEN** the tool SHALL return `success=True` with the RAG-unavailable message; the dimension mismatch SHALL be logged at ERROR level with the remediation command
