## ADDED Requirements

### Requirement: agent_loop is an AsyncGenerator yielding StreamEvent
`agent_loop(state: AgentState)` SHALL be an async generator that yields `StreamEvent` objects. It SHALL NOT return ExitReason directly — instead it SHALL set `state.exit_reason` before the generator ends.

#### Scenario: Text-only response yields text_delta events
- **WHEN** agent_loop calls adapter.call_stream() and receives text deltas
- **THEN** agent_loop SHALL yield each StreamEvent(type="text_delta") to the consumer

#### Scenario: Tool call response yields tool events then tool_result
- **WHEN** agent_loop receives tool_start/tool_delta/tool_end events from call_stream
- **THEN** it SHALL yield tool_start and tool_delta events to the consumer
- **AND** on tool_end, it SHALL dispatch the tool, then yield StreamEvent(type="tool_result", ...)

#### Scenario: Multi-turn loop yields events across all turns
- **WHEN** agent_loop runs 2 turns (LLM → tool → LLM → done)
- **THEN** the consumer SHALL receive events from both turns in sequence

#### Scenario: Exit reason set on state
- **WHEN** agent_loop completes (LLM returns no tool_calls)
- **THEN** state.exit_reason SHALL be ExitReason.COMPLETED

#### Scenario: Max turns exit
- **WHEN** turn_count reaches max_turns
- **THEN** state.exit_reason SHALL be ExitReason.MAX_TURNS and the generator SHALL end

#### Scenario: Abort exit
- **WHEN** abort_signal is set
- **THEN** state.exit_reason SHALL be ExitReason.ABORT and the generator SHALL end

#### Scenario: Error exit
- **WHEN** adapter.call_stream() raises a non-recoverable exception
- **THEN** agent_loop SHALL yield StreamEvent(type="error", content=str(exc)), set state.exit_reason=ERROR, and end

### Requirement: agent_loop accumulates LLMResponse from stream for message history
agent_loop SHALL accumulate all text_delta, thinking_delta, and tool_end events from a single call_stream into a complete assistant message dict, and append it to state.messages after the stream ends for that turn.

#### Scenario: Text accumulation
- **WHEN** call_stream yields text_delta("你"), text_delta("好"), done
- **THEN** state.messages SHALL contain an assistant message with content="你好"

#### Scenario: Tool call accumulation
- **WHEN** call_stream yields tool_start, tool_delta(s), tool_end(ToolCallRequest(...)), done
- **THEN** state.messages SHALL contain an assistant message with the complete tool_calls list

#### Scenario: Mixed text and tool calls
- **WHEN** call_stream yields text_delta("Let me check"), tool_start, tool_end(...), done
- **THEN** the assistant message SHALL have both content and tool_calls

### Requirement: Compact integration unchanged
agent_loop SHALL run micro_compact, autocompact threshold check, and blocking_limit check at the start of each turn, identical to the current non-streaming implementation. Reactive compact SHALL trigger on context_length_exceeded errors from call_stream.

#### Scenario: Micro compact runs before each call_stream
- **WHEN** a new turn begins
- **THEN** micro_compact SHALL be called on state.messages before call_stream

#### Scenario: Reactive compact on context_length_exceeded
- **WHEN** call_stream raises context_length_exceeded and has_attempted_reactive_compact is False
- **THEN** reactive_compact SHALL be called, flag set True, and the turn retried

### Requirement: run_agent_to_completion helper
`run_agent_to_completion(state: AgentState) -> ExitReason` SHALL consume all events from agent_loop(state) silently and return state.exit_reason. This is the migration path for callers that do not need streaming.

#### Scenario: Returns ExitReason after completion
- **WHEN** run_agent_to_completion is called and agent_loop yields events and ends
- **THEN** it SHALL return state.exit_reason (e.g., ExitReason.COMPLETED)

#### Scenario: All events consumed
- **WHEN** run_agent_to_completion is called
- **THEN** it SHALL iterate through ALL events from agent_loop (not break early) to ensure full execution

### Requirement: AgentState gains exit_reason field
AgentState SHALL add an `exit_reason: ExitReason | None` field, defaulting to None. agent_loop SHALL set this field before the generator ends.

#### Scenario: exit_reason initially None
- **WHEN** AgentState is created
- **THEN** exit_reason SHALL be None

#### Scenario: exit_reason set after agent_loop
- **WHEN** agent_loop completes
- **THEN** state.exit_reason SHALL be set to the appropriate ExitReason value
