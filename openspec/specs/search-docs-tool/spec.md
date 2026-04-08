## ADDED Requirements

### Requirement: SearchDocsTool provides document retrieval for agents
The system SHALL provide a `SearchDocsTool` that searches project documents via vector similarity.
- `name`: "search_docs"
- `input_schema`: `{"query": {"type": "string"}, "top_k": {"type": "integer"}}`
  - `query` is required; `top_k` is optional (default 5)
- `is_concurrency_safe`: always `True`
- `is_read_only`: always `True`

#### Scenario: Successful search
- **WHEN** search_docs is called with `{"query": "market analysis"}`
- **THEN** it SHALL retrieve relevant chunks from the current project and return `ToolResult(output=<formatted results>, success=True)`

#### Scenario: Search with custom top_k
- **WHEN** search_docs is called with `{"query": "revenue", "top_k": 3}`
- **THEN** it SHALL return at most 3 results

#### Scenario: No results found
- **WHEN** search_docs is called and no relevant chunks exist
- **THEN** it SHALL return `ToolResult(output="No relevant documents found.", success=True)`

#### Scenario: Project isolation via ToolContext
- **WHEN** search_docs is called
- **THEN** it SHALL use `tool_context.project_id` to restrict results to the current project
