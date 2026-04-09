## ADDED Requirements

### Requirement: StreamEvent dataclass defines unified streaming event
The system SHALL define a `StreamEvent` dataclass in `src/streaming/events.py` with fields: `type` (str), `content` (str, default ""), `tool_call_id` (str, default ""), `name` (str, default ""), `tool_call` (ToolCallRequest | None, default None), `output` (str, default ""), `success` (bool, default True), `usage` (Usage | None, default None), `finish_reason` (str, default "").

#### Scenario: StreamEvent construction with text_delta
- **WHEN** `StreamEvent(type="text_delta", content="你好")` is created
- **THEN** type SHALL be "text_delta", content SHALL be "你好", all other fields SHALL be defaults

#### Scenario: StreamEvent construction with tool_end
- **WHEN** `StreamEvent(type="tool_end", tool_call=ToolCallRequest(id="x", name="read_file", arguments={"path":"/a"}))` is created
- **THEN** tool_call SHALL contain the complete ToolCallRequest object

#### Scenario: StreamEvent construction with done
- **WHEN** `StreamEvent(type="done", finish_reason="stop")` is created
- **THEN** finish_reason SHALL be "stop"

### Requirement: StreamEvent type values are enumerated
StreamEvent.type SHALL be one of: `text_delta`, `thinking_delta`, `tool_start`, `tool_delta`, `tool_end`, `tool_result`, `usage`, `done`, `error`. Any other value is invalid.

#### Scenario: Valid type values
- **WHEN** StreamEvent is created with type="text_delta"
- **THEN** it SHALL be accepted

#### Scenario: All nine event types are defined
- **WHEN** the complete list of valid event types is enumerated
- **THEN** it SHALL contain exactly: text_delta, thinking_delta, tool_start, tool_delta, tool_end, tool_result, usage, done, error

### Requirement: OpenAICompatAdapter.call_stream() yields StreamEvent from OpenAI SSE
`OpenAICompatAdapter.call_stream(messages, tools=None, **kwargs)` SHALL return `AsyncIterator[StreamEvent]`. It SHALL send a request with `stream=True`, parse SSE lines, and yield StreamEvent for each delta.

#### Scenario: Text delta from OpenAI SSE
- **WHEN** an SSE chunk contains `choices[0].delta.content = "你好"`
- **THEN** call_stream SHALL yield `StreamEvent(type="text_delta", content="你好")`

#### Scenario: Thinking delta from OpenAI SSE
- **WHEN** an SSE chunk contains `choices[0].delta.reasoning_content = "Let me think"`
- **THEN** call_stream SHALL yield `StreamEvent(type="thinking_delta", content="Let me think")`

#### Scenario: Tool call start from OpenAI SSE
- **WHEN** an SSE chunk contains a new tool_call index with function.name
- **THEN** call_stream SHALL yield `StreamEvent(type="tool_start", tool_call_id=id, name=name)`

#### Scenario: Tool call argument delta from OpenAI SSE
- **WHEN** an SSE chunk contains tool_calls[idx].function.arguments with a JSON fragment
- **THEN** call_stream SHALL yield `StreamEvent(type="tool_delta", content=fragment)`

#### Scenario: Tool call end at stream completion
- **WHEN** the SSE stream ends (data: [DONE]) and accumulated tool_call arguments form valid JSON
- **THEN** call_stream SHALL yield `StreamEvent(type="tool_end", tool_call=ToolCallRequest(...))` with the complete parsed arguments

#### Scenario: Usage from final chunk
- **WHEN** the last SSE chunk contains a usage object
- **THEN** call_stream SHALL yield `StreamEvent(type="usage", usage=Usage(...))`

#### Scenario: Done event at end
- **WHEN** the SSE stream completes
- **THEN** call_stream SHALL yield `StreamEvent(type="done", finish_reason=...)` as the last event

#### Scenario: Multiple tool calls in single response
- **WHEN** the LLM returns two tool_calls (index 0 and 1) in the SSE stream
- **THEN** call_stream SHALL yield tool_start, tool_delta(s), and tool_end for each, ordered by index

#### Scenario: Empty content deltas are skipped
- **WHEN** an SSE chunk contains `delta.content = ""` or `delta.content = null`
- **THEN** call_stream SHALL NOT yield a text_delta event

### Requirement: AnthropicAdapter.call_stream() yields StreamEvent from Anthropic SSE
`AnthropicAdapter.call_stream(messages, tools=None, **kwargs)` SHALL return `AsyncIterator[StreamEvent]`. It SHALL send a request with `stream=True`, parse Anthropic SSE events, and yield StreamEvent for each delta.

#### Scenario: Text delta from Anthropic SSE
- **WHEN** an SSE event `content_block_delta` with `delta.type="text_delta"` arrives
- **THEN** call_stream SHALL yield `StreamEvent(type="text_delta", content=delta.text)`

#### Scenario: Thinking delta from Anthropic SSE
- **WHEN** an SSE event `content_block_delta` with `delta.type="thinking_delta"` arrives
- **THEN** call_stream SHALL yield `StreamEvent(type="thinking_delta", content=delta.thinking)`

#### Scenario: Tool use block start
- **WHEN** an SSE event `content_block_start` with `content_block.type="tool_use"` arrives
- **THEN** call_stream SHALL yield `StreamEvent(type="tool_start", tool_call_id=id, name=name)`

#### Scenario: Tool argument delta from Anthropic SSE
- **WHEN** an SSE event `content_block_delta` with `delta.type="input_json_delta"` arrives
- **THEN** call_stream SHALL yield `StreamEvent(type="tool_delta", content=delta.partial_json)`

#### Scenario: Tool use block stop
- **WHEN** an SSE event `content_block_stop` arrives for a tool_use block
- **THEN** call_stream SHALL yield `StreamEvent(type="tool_end", tool_call=ToolCallRequest(...))` with accumulated arguments parsed as JSON

#### Scenario: Usage from message_start and message_delta
- **WHEN** `message_start` contains `usage.input_tokens` and `message_delta` contains `usage.output_tokens`
- **THEN** call_stream SHALL yield `StreamEvent(type="usage", usage=Usage(input_tokens=..., output_tokens=...))` at stream end

#### Scenario: Done event maps stop_reason
- **WHEN** Anthropic `message_delta` has `stop_reason="tool_use"`
- **THEN** call_stream SHALL yield `StreamEvent(type="done", finish_reason="tool_calls")`
- **WHEN** `stop_reason="end_turn"`
- **THEN** finish_reason SHALL be "stop"

#### Scenario: Anthropic thinking requires beta header
- **WHEN** call_stream is invoked with `thinking` in kwargs
- **THEN** the request SHALL include `anthropic-beta: interleaved-thinking-2025-05-14` header

### Requirement: call_stream retries on transient errors before streaming begins
`call_stream()` SHALL retry on 429 and 5xx status codes with exponential backoff (same as call()), up to 3 attempts. Once the SSE stream has started (status 200), mid-stream errors SHALL yield `StreamEvent(type="error", content=...)` instead of retrying.

#### Scenario: Retry on 429 before stream starts
- **WHEN** the initial HTTP request returns 429
- **THEN** call_stream SHALL retry with exponential backoff, up to 3 attempts

#### Scenario: Mid-stream connection error
- **WHEN** the SSE stream disconnects after receiving partial data
- **THEN** call_stream SHALL yield `StreamEvent(type="error", content="Stream disconnected: ...")` and stop

### Requirement: API SSE output format specification
The system SHALL define the following SSE wire format for Phase 6 API layer. Each StreamEvent maps to one SSE message: `event: {type}\ndata: {json}\n\n`.

#### Scenario: text_delta SSE format
- **WHEN** StreamEvent(type="text_delta", content="你好") is serialized to SSE
- **THEN** output SHALL be `event: text_delta\ndata: {"content": "你好"}\n\n`

#### Scenario: tool_start SSE format
- **WHEN** StreamEvent(type="tool_start", tool_call_id="call_xxx", name="read_file") is serialized
- **THEN** output SHALL be `event: tool_start\ndata: {"tool_call_id": "call_xxx", "name": "read_file"}\n\n`

#### Scenario: tool_result SSE format
- **WHEN** StreamEvent(type="tool_result", tool_call_id="call_xxx", output="content", success=True) is serialized
- **THEN** output SHALL be `event: tool_result\ndata: {"tool_call_id": "call_xxx", "output": "content", "success": true}\n\n`

#### Scenario: done SSE format
- **WHEN** StreamEvent(type="done", finish_reason="completed") is serialized
- **THEN** output SHALL be `event: done\ndata: {"finish_reason": "completed"}\n\n`
