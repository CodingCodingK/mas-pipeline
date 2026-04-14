# Agent Loop

## Purpose
Drive an agent's think→act→observe loop: call LLM, dispatch tool calls, append results, and manage exit conditions (done, max turns, token limits, interrupts).
## Requirements
### Requirement: AgentState holds all runtime dependencies
AgentState SHALL be a mutable dataclass containing messages, tools (ToolRegistry), adapter (LLMAdapter), orchestrator (ToolOrchestrator), and tool_context (ToolContext). Identity fields (agent_id, run_id, project_id) SHALL be accessed via tool_context, not duplicated on AgentState. AgentState SHALL also hold turn_count, max_turns, and has_attempted_reactive_compact. AgentState SHALL also hold `tool_use_count: int = 0` and `cumulative_tokens: int = 0`, both initialized to 0 and incremented by `agent_loop` as the sub-agent consumes resources.

#### Scenario: AgentState construction with all dependencies
- **WHEN** an AgentState is created with adapter, tools, orchestrator, tool_context, and messages
- **THEN** all fields are accessible as attributes and messages is a mutable list[dict]
- **AND** tool_use_count and cumulative_tokens SHALL default to 0

#### Scenario: Runtime field mutation
- **WHEN** code assigns a new adapter to state.adapter during execution
- **THEN** subsequent agent_loop iterations use the new adapter

#### Scenario: Identity accessed via tool_context
- **WHEN** agent_id or run_id is needed
- **THEN** it SHALL be accessed as state.tool_context.agent_id, not state.agent_id

#### Scenario: Turn-level accumulation
- **WHEN** agent_loop completes one turn that issued 3 tool calls and the LLM response reported usage.total_tokens=1800
- **THEN** state.tool_use_count SHALL be incremented by 3 and state.cumulative_tokens SHALL be incremented by 1800

### Requirement: ExitReason enum covers Phase 1 exit conditions
ExitReason SHALL be a str-based Enum with values: COMPLETED, MAX_TURNS, ABORT, ERROR, TOKEN_LIMIT. TOKEN_LIMIT indicates the agent exceeded its context window and compact could not recover.

#### Scenario: ExitReason values are strings
- **WHEN** ExitReason.COMPLETED is compared to the string "completed"
- **THEN** the comparison SHALL be true (str Enum)

#### Scenario: ExitReason serialization
- **WHEN** ExitReason is serialized to JSON
- **THEN** it SHALL produce a plain string value

#### Scenario: TOKEN_LIMIT value
- **WHEN** ExitReason.TOKEN_LIMIT is accessed
- **THEN** it SHALL equal the string "token_limit"

### Requirement: ReAct loop drives LLM and tool execution
agent_loop(state) SHALL be an AsyncGenerator that yields StreamEvent. It SHALL implement a while-True loop that: (1) calls state.adapter.call_stream() and yields events to the consumer while accumulating the response, (2) appends the accumulated assistant message to state.messages, (3) if no tool_calls, sets state.exit_reason=COMPLETED and returns, (4) dispatches tool calls via state.orchestrator and yields tool_result events, (5) appends tool result messages, (6) increments turn_count and checks max_turns.

#### Scenario: Single-turn completion (no tool calls)
- **WHEN** LLM stream yields text deltas and done with no tool calls
- **THEN** agent_loop yields the text_delta events, appends the assistant message, sets state.exit_reason=COMPLETED, and ends

#### Scenario: Multi-turn with tool calls
- **WHEN** LLM stream yields tool_end, then on next call yields text and done
- **THEN** agent_loop dispatches tools, yields tool_result events, calls LLM again, yields text events, and sets exit_reason=COMPLETED

#### Scenario: Tool results fed back to LLM
- **WHEN** orchestrator returns ToolResult for each tool_call
- **THEN** each result is appended as a tool message with matching tool_call_id, and a StreamEvent(type="tool_result") is yielded for each

### Requirement: Max turns exit condition
agent_loop SHALL increment state.turn_count after each tool execution round and set state.exit_reason=MAX_TURNS when turn_count reaches max_turns, then end the generator.

#### Scenario: Reaching max turns
- **WHEN** turn_count reaches max_turns after tool execution
- **THEN** state.exit_reason SHALL be MAX_TURNS and the generator SHALL end without calling LLM again

#### Scenario: Default max turns is 50
- **WHEN** AgentState is created without specifying max_turns
- **THEN** max_turns defaults to 50

### Requirement: Abort signal exits loop
agent_loop SHALL check state.tool_context.abort_signal at two points: before calling LLM and after tool execution. If the signal is set, it SHALL return ExitReason.ABORT.

#### Scenario: Abort before LLM call
- **WHEN** abort_signal is set before agent_loop calls the adapter
- **THEN** agent_loop returns ExitReason.ABORT without calling the adapter

#### Scenario: Abort after tool execution
- **WHEN** abort_signal is set during tool execution
- **THEN** agent_loop returns ExitReason.ABORT after tool results are appended

#### Scenario: No abort signal configured
- **WHEN** tool_context.abort_signal is None
- **THEN** agent_loop SHALL skip abort checks and continue normally

### Requirement: LLM errors return ERROR exit reason
agent_loop SHALL catch exceptions from state.adapter.call() and return ExitReason.ERROR. Retries are handled at the adapter layer; loop-level exceptions are non-recoverable.

#### Scenario: Adapter raises exception
- **WHEN** state.adapter.call() raises any Exception
- **THEN** agent_loop returns ExitReason.ERROR

#### Scenario: Adapter retry exhaustion
- **WHEN** adapter retries 429/5xx 3 times and still fails, raising an exception
- **THEN** agent_loop catches it and returns ExitReason.ERROR

### Requirement: Messages use OpenAI dict format
state.messages SHALL be a list of dicts in OpenAI chat completion format. Assistant messages SHALL include tool_calls with arguments as dict (not JSON string). Tool result messages SHALL use role "tool" with tool_call_id. A non-standard "thinking" field MAY be present on assistant messages.

#### Scenario: Assistant message with tool calls
- **WHEN** format_assistant_msg receives an LLMResponse with tool_calls
- **THEN** the returned dict has role "assistant" and tool_calls list with arguments as dict

#### Scenario: Assistant message with content only
- **WHEN** format_assistant_msg receives an LLMResponse with content and no tool_calls
- **THEN** the returned dict has role "assistant" and content string, no tool_calls key

#### Scenario: Tool result message
- **WHEN** format_tool_msg receives a tool_call_id and ToolResult
- **THEN** the returned dict has role "tool", the matching tool_call_id, and result.output as content

#### Scenario: User message
- **WHEN** format_user_msg receives a text string
- **THEN** the returned dict has role "user" and the text as content

#### Scenario: Thinking field preserved
- **WHEN** LLMResponse has thinking content
- **THEN** format_assistant_msg includes a "thinking" field in the dict

### Requirement: Compact hooks are placeholder only
agent_loop SHALL integrate compact processing at three positions:

1. **Before LLM call**: call `micro_compact(state.messages)` to clear old tool results. Then call `estimate_tokens(state.messages)`. If tokens exceed `blocking_limit`, return `ExitReason.TOKEN_LIMIT`. If tokens exceed `autocompact_threshold`, call `auto_compact(state.messages, state.adapter, model)` and replace `state.messages` with the result. If still above `blocking_limit` after autocompact, return `ExitReason.TOKEN_LIMIT`.

2. **After LLM error**: if LLM returns a `context_length_exceeded` error and `state.has_attempted_reactive_compact` is False, call `reactive_compact(state.messages, state.adapter, model)`, replace `state.messages`, set `has_attempted_reactive_compact = True`, and `continue` the loop. If `has_attempted_reactive_compact` is already True, return `ExitReason.TOKEN_LIMIT`.

AgentState SHALL include `has_attempted_reactive_compact` field defaulting to False.

#### Scenario: Microcompact runs every turn
- **WHEN** agent_loop begins a new iteration
- **THEN** `micro_compact` SHALL be called on `state.messages` before the LLM call

#### Scenario: Autocompact triggered by threshold
- **WHEN** `estimate_tokens(state.messages)` exceeds `autocompact_threshold`
- **THEN** `auto_compact` SHALL be called and `state.messages` SHALL be replaced with the compacted result

#### Scenario: Blocking limit exits loop
- **WHEN** tokens exceed `blocking_limit` even after autocompact
- **THEN** agent_loop SHALL return `ExitReason.TOKEN_LIMIT`

#### Scenario: Reactive compact on first context_length_exceeded
- **WHEN** LLM raises context_length_exceeded and `has_attempted_reactive_compact` is False
- **THEN** `reactive_compact` SHALL be called, flag set to True, and loop continues

#### Scenario: Second context_length_exceeded exits
- **WHEN** LLM raises context_length_exceeded and `has_attempted_reactive_compact` is True
- **THEN** agent_loop SHALL return `ExitReason.TOKEN_LIMIT`

### Requirement: Agent loop emits llm_call telemetry event after each LLM invocation
After each successful or failed LLM call in `agent_loop`, the system SHALL call `telemetry_collector.record_llm_call(...)` with the provider, model, token counts from `LLMResponse.usage`, measured latency, and finish reason.

Emission SHALL happen after the LLM response is received (or after the exception is raised in failure cases — failure path emits both a `llm_call` event with `finish_reason='error'` and a separate `error` event with `source='llm'`).

Emission SHALL NOT block the agent loop: the collector's `record_llm_call` is a synchronous queue append that returns in O(1).

Emission SHALL be a no-op when `telemetry.enabled=False`.

#### Scenario: Successful LLM call emits event
- **WHEN** `agent_loop` completes one LLM invocation with a valid response
- **THEN** exactly one `llm_call` event SHALL be emitted with tokens from `response.usage`, `latency_ms` measured from pre-call to post-call, and `finish_reason` from the response

#### Scenario: Failed LLM call emits both llm_call and error events
- **WHEN** an LLM invocation raises an exception (rate limit, network error, etc.)
- **THEN** one `llm_call` event SHALL be emitted with `finish_reason='error'` and best-effort token counts (may be 0)
- **AND** one `error` event SHALL be emitted with `source='llm'`, `error_type` set to the exception class, and the stacktrace hash

#### Scenario: Telemetry disabled path adds zero latency
- **WHEN** `telemetry.enabled=False` and an LLM call completes
- **THEN** no event SHALL be queued
- **AND** the agent loop SHALL proceed with sub-microsecond overhead from the bool check

### Requirement: run_agent_to_completion returns a rich result
`run_agent_to_completion(state) -> AgentRunResult` SHALL consume all events from `agent_loop(state)` and return a dataclass containing:
- `exit_reason: ExitReason`
- `messages: list[dict]` — reference to `state.messages` (post-loop)
- `final_output: str` — extracted via `extract_final_output(state.messages)`
- `tool_use_count: int` — from `state.tool_use_count`
- `cumulative_tokens: int` — from `state.cumulative_tokens`
- `duration_ms: int` — measured by `run_agent_to_completion` via `time.monotonic()` wrapping the loop

Callers SHALL NOT need to reach into `state.*` fields themselves; the rich result is the single canonical handoff.

#### Scenario: Successful completion returns populated result
- **WHEN** run_agent_to_completion is called on a state whose agent finishes normally after 3 turns with 5 tool calls and ~8000 tokens consumed
- **THEN** the returned AgentRunResult SHALL have exit_reason=COMPLETED, final_output=<last assistant text>, tool_use_count=5, cumulative_tokens=8000, duration_ms>0, and messages equal to state.messages

#### Scenario: Error path still returns result
- **WHEN** run_agent_to_completion is called on a state whose agent hits ExitReason.ERROR after partial execution
- **THEN** the returned AgentRunResult SHALL have exit_reason=ERROR, messages containing whatever partial transcript accumulated, and the three statistics reflecting partial consumption (possibly 0)

#### Scenario: Duration measured at wrapper level
- **WHEN** run_agent_to_completion wraps a 500ms agent_loop run
- **THEN** duration_ms SHALL be approximately 500 (±100ms tolerance), measured with time.monotonic() around the async generator consumption

### Requirement: agent_loop accumulates turn-level statistics
At the end of each successful turn, `agent_loop` SHALL:
1. Increment `state.tool_use_count` by `len(tool_calls)` where `tool_calls` is the list dispatched for that turn (before `max_turns` check)
2. Increment `state.cumulative_tokens` by `usage.total_tokens` from the LLM response for that turn (default 0 if unreported)

These increments SHALL happen after the LLM response is processed and the assistant message is appended, in the same scope where `state.turn_count` is incremented.

#### Scenario: No tool calls in a turn
- **WHEN** a turn ends with no tool calls (pure text completion)
- **THEN** state.tool_use_count SHALL NOT change and state.cumulative_tokens SHALL still be incremented by that turn's usage

#### Scenario: Multiple tool calls in a turn
- **WHEN** a turn ends with 4 parallel tool calls
- **THEN** state.tool_use_count SHALL be incremented by exactly 4

#### Scenario: Missing usage info defaults to 0
- **WHEN** an LLM response has no usage information (usage.total_tokens is 0 or None)
- **THEN** state.cumulative_tokens SHALL NOT crash, incrementing by 0

