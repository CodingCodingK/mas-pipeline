## ADDED Requirements

### Requirement: AnthropicAdapter implements LLMAdapter
The system SHALL provide an `AnthropicAdapter` class that extends `LLMAdapter` and communicates with the Anthropic Messages API at `{api_base}/v1/messages`.

#### Scenario: Adapter initialization
- **WHEN** `AnthropicAdapter(api_base, api_key, model)` is created
- **THEN** it SHALL configure an HTTP client with `x-api-key` header (not `Authorization: Bearer`) and `anthropic-version: 2023-06-01` header

#### Scenario: Basic text response
- **WHEN** `call(messages, tools=None)` is invoked with a simple user message
- **THEN** it SHALL return `LLMResponse(content=<text>, tool_calls=[], finish_reason="stop")`

### Requirement: Request construction converts OpenAI format to Anthropic format
`AnthropicAdapter._build_request(messages, tools, **kwargs)` SHALL convert internal OpenAI-format messages to Anthropic Messages API format.

#### Scenario: System message extraction
- **WHEN** messages contain `{"role": "system", "content": "You are..."}` as the first message
- **THEN** the request SHALL have `system: "You are..."` as a top-level parameter, and the system message SHALL be removed from the `messages` array

#### Scenario: Text-only user message
- **WHEN** a user message has `content` as a plain string
- **THEN** it SHALL be sent as `{"role": "user", "content": "the text"}`

#### Scenario: Multimodal user message with image
- **WHEN** a user message has `content` as a list containing `{"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}}`
- **THEN** it SHALL be converted to `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR..."}}`

#### Scenario: Tool calls in assistant message
- **WHEN** an assistant message has `tool_calls: [{"id": "tc_1", "function": {"name": "read_file", "arguments": {"path": "/tmp"}}}]`
- **THEN** it SHALL be converted to assistant content block `{"type": "tool_use", "id": "tc_1", "name": "read_file", "input": {"path": "/tmp"}}`

#### Scenario: Tool result message
- **WHEN** messages contain `{"role": "tool", "tool_call_id": "tc_1", "content": "file contents..."}`
- **THEN** it SHALL be converted to a user message with content block `{"type": "tool_result", "tool_use_id": "tc_1", "content": "file contents..."}`

#### Scenario: Adjacent same-role messages merged
- **WHEN** messages contain two consecutive user messages (e.g., a text message followed by a tool_result)
- **THEN** they SHALL be merged into a single user message with multiple content blocks

#### Scenario: Tools converted to Anthropic format
- **WHEN** `tools` list contains OpenAI-format tool definitions `{"type": "function", "function": {"name": "x", "description": "y", "parameters": {...}}}`
- **THEN** they SHALL be converted to Anthropic format `{"name": "x", "description": "y", "input_schema": {...}}`

### Requirement: Response parsing converts Anthropic format to LLMResponse
`AnthropicAdapter._parse_response(data)` SHALL convert Anthropic response format to `LLMResponse`.

#### Scenario: Text content block
- **WHEN** response contains `{"type": "text", "text": "Hello"}`
- **THEN** `LLMResponse.content` SHALL be `"Hello"`

#### Scenario: Multiple text blocks concatenated
- **WHEN** response contains multiple text content blocks
- **THEN** `LLMResponse.content` SHALL be all text blocks joined with newlines

#### Scenario: Tool use content block
- **WHEN** response contains `{"type": "tool_use", "id": "tc_1", "name": "read_file", "input": {"path": "/tmp"}}`
- **THEN** `LLMResponse.tool_calls` SHALL contain `ToolCallRequest(id="tc_1", name="read_file", arguments={"path": "/tmp"})`

#### Scenario: Thinking content block
- **WHEN** response contains `{"type": "thinking", "thinking": "Let me analyze..."}`
- **THEN** `LLMResponse.thinking` SHALL be `"Let me analyze..."`

#### Scenario: Stop reason mapping
- **WHEN** Anthropic response has `stop_reason: "end_turn"`
- **THEN** `LLMResponse.finish_reason` SHALL be `"stop"`

#### Scenario: Tool use stop reason
- **WHEN** Anthropic response has `stop_reason: "tool_use"`
- **THEN** `LLMResponse.finish_reason` SHALL be `"tool_calls"`

#### Scenario: Usage parsing
- **WHEN** Anthropic response has `usage: {"input_tokens": 100, "output_tokens": 50}`
- **THEN** `LLMResponse.usage` SHALL be `Usage(input_tokens=100, output_tokens=50, thinking_tokens=0)`

### Requirement: Retry on transient errors
`AnthropicAdapter` SHALL retry on HTTP 429 and 5xx status codes using exponential backoff (1s, 2s, 4s), up to 3 attempts. Non-retryable errors SHALL raise immediately.

#### Scenario: Retry on rate limit
- **WHEN** the API returns HTTP 429
- **THEN** the adapter retries with exponential backoff, up to 3 times

#### Scenario: No retry on 400
- **WHEN** the API returns HTTP 400
- **THEN** the adapter raises `LLMAPIError` immediately without retrying

#### Scenario: All retries exhausted
- **WHEN** all 3 retry attempts fail
- **THEN** the adapter raises the last error

### Requirement: Extended thinking support
`AnthropicAdapter` SHALL support Anthropic extended thinking when enabled via kwargs.

#### Scenario: Thinking enabled via kwargs
- **WHEN** `call()` is invoked with `thinking={"type": "enabled", "budget_tokens": 10000}`
- **THEN** the request SHALL include the thinking parameter and set `anthropic-beta` header appropriately

#### Scenario: Thinking tokens in usage
- **WHEN** response includes thinking token usage (in `usage` or via thinking block metadata)
- **THEN** `Usage.thinking_tokens` SHALL reflect the thinking token consumption
