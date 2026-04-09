## MODIFIED Requirements

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
agent_loop SHALL check state.tool_context.abort_signal at two points: before calling LLM and after tool execution. If the signal is set, it SHALL set state.exit_reason=ABORT and end the generator.

#### Scenario: Abort before LLM call
- **WHEN** abort_signal is set before agent_loop calls call_stream
- **THEN** state.exit_reason SHALL be ABORT and generator ends without calling the adapter

#### Scenario: Abort after tool execution
- **WHEN** abort_signal is set during tool execution
- **THEN** state.exit_reason SHALL be ABORT after tool results are appended

### Requirement: LLM errors set ERROR exit reason
agent_loop SHALL catch exceptions from state.adapter.call_stream(). Non-recoverable errors SHALL yield StreamEvent(type="error") and set state.exit_reason=ERROR.

#### Scenario: Adapter raises exception
- **WHEN** state.adapter.call_stream() raises any non-context-length Exception
- **THEN** agent_loop SHALL yield StreamEvent(type="error", content=str(exc)) and set exit_reason=ERROR

#### Scenario: Adapter retry exhaustion
- **WHEN** adapter retries 429/5xx 3 times and still fails, raising an exception
- **THEN** agent_loop catches it, yields error event, and sets exit_reason=ERROR
