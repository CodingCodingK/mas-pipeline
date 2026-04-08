## ADDED Requirements

### Requirement: WebSearchTool provides structured web search via Tavily API
`WebSearchTool` SHALL be a built-in tool (extends Tool ABC) with name="web_search" that calls Tavily Search API and returns structured results.

#### Scenario: Basic search
- **WHEN** web_search is called with params {"query": "RAG optimization techniques"}
- **THEN** it SHALL call Tavily API with the query
- **AND** return a ToolResult with success=True containing formatted search results

#### Scenario: Search with max_results
- **WHEN** web_search is called with params {"query": "RAG", "max_results": 3}
- **THEN** it SHALL return at most 3 results

### Requirement: WebSearchTool input schema
The tool's input_schema SHALL define: `query` (string, required) and `max_results` (integer, optional, default 5).

#### Scenario: Valid input
- **WHEN** params contain {"query": "test"}
- **THEN** validation SHALL pass

#### Scenario: Missing query
- **WHEN** params contain {} (no query)
- **THEN** validation SHALL fail

### Requirement: WebSearchTool output format
ToolResult.output SHALL contain one block per result, each with title, URL, and content snippet. The format SHALL be human-readable plain text that LLMs can directly consume.

#### Scenario: Multiple results
- **WHEN** Tavily returns 3 results
- **THEN** output SHALL contain 3 formatted blocks, each with title, url, and content

#### Scenario: No results
- **WHEN** Tavily returns zero results
- **THEN** output SHALL contain a message indicating no results found

### Requirement: WebSearchTool handles API errors gracefully
When Tavily API returns an error (network failure, invalid key, rate limit), the tool SHALL return ToolResult with success=False and a descriptive error message.

#### Scenario: Invalid API key
- **WHEN** Tavily returns 401
- **THEN** ToolResult.success SHALL be False
- **AND** output SHALL contain "Invalid API key" or similar message

#### Scenario: Rate limit exceeded
- **WHEN** Tavily returns 429
- **THEN** ToolResult.success SHALL be False
- **AND** output SHALL indicate rate limit exceeded

### Requirement: WebSearchTool reads API key from config
The tool SHALL read the Tavily API key from `settings.yaml` via the config system (`tavily.api_key` with `${TAVILY_API_KEY}` env var substitution).

#### Scenario: API key from environment
- **WHEN** TAVILY_API_KEY is set in environment
- **THEN** the tool SHALL use that key for Tavily API requests

### Requirement: WebSearchTool is read-only and concurrency-safe
`is_read_only(params)` and `is_concurrency_safe(params)` SHALL both return True.

#### Scenario: Concurrent searches
- **WHEN** ToolOrchestrator dispatches 3 web_search calls concurrently
- **THEN** all 3 SHALL execute in parallel without conflict
