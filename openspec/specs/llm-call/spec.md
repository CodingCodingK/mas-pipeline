## ADDED Requirements

### Requirement: LLM call returns standardized response
The system SHALL return all LLM API responses as a `LLMResponse` dataclass containing: `content` (str | None), `tool_calls` (list[ToolCallRequest]), `finish_reason` (str), `usage` (Usage), `thinking` (str | None).

#### Scenario: Normal text response
- **WHEN** the LLM returns a text response without tool calls
- **THEN** `LLMResponse.content` contains the text, `tool_calls` is empty, `finish_reason` is "stop"

#### Scenario: Tool call response
- **WHEN** the LLM returns one or more tool calls
- **THEN** `LLMResponse.tool_calls` contains `ToolCallRequest` objects with `id`, `name`, and `arguments` (dict), and `content` MAY be None

#### Scenario: Thinking response (DeepSeek)
- **WHEN** the LLM returns a response with thinking/reasoning content
- **THEN** `LLMResponse.thinking` contains the thinking text

### Requirement: Usage tracks token consumption uniformly
The system SHALL normalize all provider-specific token fields into a `Usage` dataclass with `input_tokens` (int), `output_tokens` (int), `thinking_tokens` (int, default 0).

#### Scenario: OpenAI token mapping
- **WHEN** OpenAI API returns `prompt_tokens` and `completion_tokens`
- **THEN** `Usage.input_tokens` equals `prompt_tokens` and `Usage.output_tokens` equals `completion_tokens`

#### Scenario: DeepSeek thinking tokens
- **WHEN** DeepSeek API returns thinking/reasoning token counts
- **THEN** `Usage.thinking_tokens` reflects the thinking token consumption

### Requirement: LLMAdapter defines async call interface
The system SHALL define an abstract base class `LLMAdapter` with two async methods:
- `call(messages, tools=None, **kwargs) -> LLMResponse` (existing, unchanged)
- `call_stream(messages, tools=None, **kwargs) -> AsyncIterator[StreamEvent]` (new)

Both methods SHALL be abstract. Subclasses MUST implement both.

#### Scenario: Subclass must implement call
- **WHEN** a subclass of `LLMAdapter` does not implement `call()`
- **THEN** instantiation raises `TypeError`

#### Scenario: Subclass must implement call_stream
- **WHEN** a subclass of `LLMAdapter` does not implement `call_stream()`
- **THEN** instantiation raises `TypeError`

#### Scenario: call() behavior unchanged
- **WHEN** `call()` is invoked
- **THEN** it SHALL return a complete `LLMResponse` object, identical to pre-streaming behavior

### Requirement: OpenAI-compatible adapter handles multiple providers
The system SHALL implement `OpenAICompatAdapter` that works with any provider using OpenAI-compatible API format (OpenAI, DeepSeek, Ollama, Gemini).

#### Scenario: Call with api_key and api_base
- **WHEN** `OpenAICompatAdapter` is initialized with an `api_base` and `api_key`
- **THEN** it sends requests to `{api_base}/chat/completions` with the `api_key` in Authorization header

#### Scenario: Tools passed to API
- **WHEN** `call()` is invoked with a `tools` list
- **THEN** the tools are included in the request body in OpenAI function-calling format

#### Scenario: kwargs forwarded to request
- **WHEN** `call()` is invoked with `temperature=0.5` or `max_tokens=2000`
- **THEN** those parameters are included in the API request body

### Requirement: Retry on transient errors
The system SHALL retry LLM API calls on 429 and 5xx status codes using exponential backoff (1s, 2s, 4s), up to 3 attempts.

#### Scenario: Retry on rate limit
- **WHEN** the API returns HTTP 429
- **THEN** the system waits with exponential backoff and retries, up to 3 times

#### Scenario: Retry on server error
- **WHEN** the API returns HTTP 500, 502, 503, or 504
- **THEN** the system waits with exponential backoff and retries, up to 3 times

#### Scenario: No retry on client error
- **WHEN** the API returns HTTP 400, 401, or 403
- **THEN** the system raises an error immediately without retrying

#### Scenario: All retries exhausted
- **WHEN** all 3 retry attempts fail
- **THEN** the system raises the last error to the caller
