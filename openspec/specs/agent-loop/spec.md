## ADDED Requirements

### Requirement: AgentState holds all runtime dependencies
AgentState SHALL be a mutable dataclass containing messages, tools (ToolRegistry), adapter (LLMAdapter), orchestrator (ToolOrchestrator), and tool_context (ToolContext). Identity fields (agent_id, run_id, project_id) SHALL be accessed via tool_context, not duplicated on AgentState. AgentState SHALL also hold turn_count, max_turns, and has_attempted_reactive_compact.

#### Scenario: AgentState construction with all dependencies
- **WHEN** an AgentState is created with adapter, tools, orchestrator, tool_context, and messages
- **THEN** all fields are accessible as attributes and messages is a mutable list[dict]

#### Scenario: Runtime field mutation
- **WHEN** code assigns a new adapter to state.adapter during execution
- **THEN** subsequent agent_loop iterations use the new adapter

#### Scenario: Identity accessed via tool_context
- **WHEN** agent_id or run_id is needed
- **THEN** it SHALL be accessed as state.tool_context.agent_id, not state.agent_id

### Requirement: ExitReason enum covers Phase 1 exit conditions
ExitReason SHALL be a str-based Enum with values: COMPLETED, MAX_TURNS, ABORT, ERROR. The enum SHALL be extensible for future phases (TOKEN_LIMIT in Phase 3, HOOK_STOPPED in Phase 5).

#### Scenario: ExitReason values are strings
- **WHEN** ExitReason.COMPLETED is compared to the string "completed"
- **THEN** the comparison SHALL be true (str Enum)

#### Scenario: ExitReason serialization
- **WHEN** ExitReason is serialized to JSON
- **THEN** it SHALL produce a plain string value

### Requirement: ReAct loop drives LLM and tool execution
agent_loop(state) SHALL implement a while-True loop that: (1) calls state.adapter with state.messages and tool definitions, (2) appends the assistant message, (3) if no tool_calls returns COMPLETED, (4) dispatches tool calls via state.orchestrator, (5) appends tool result messages, (6) increments turn_count and checks max_turns.

#### Scenario: Single-turn completion (no tool calls)
- **WHEN** LLM returns a response with no tool_calls
- **THEN** agent_loop appends the assistant message and returns ExitReason.COMPLETED

#### Scenario: Multi-turn with tool calls
- **WHEN** LLM returns tool_calls, then on next call returns no tool_calls
- **THEN** agent_loop executes tools, appends results, calls LLM again, and returns COMPLETED after 2 iterations

#### Scenario: Tool results fed back to LLM
- **WHEN** orchestrator returns ToolResult for each tool_call
- **THEN** each result is appended as a tool message with matching tool_call_id before the next LLM call

### Requirement: Max turns exit condition
agent_loop SHALL increment state.turn_count after each tool execution round and return ExitReason.MAX_TURNS when turn_count reaches max_turns.

#### Scenario: Reaching max turns
- **WHEN** turn_count reaches max_turns after tool execution
- **THEN** agent_loop returns ExitReason.MAX_TURNS without calling LLM again

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
agent_loop SHALL contain comment placeholders at three positions: (1) microcompact + autocompact + blocking_limit check before LLM call, (2) reactive compact after LLM returns prompt_too_long error. AgentState SHALL include has_attempted_reactive_compact field defaulting to False.

#### Scenario: Compact placeholders do not affect execution
- **WHEN** agent_loop runs in Phase 1
- **THEN** compact placeholder comments are present but no compact logic executes

#### Scenario: has_attempted_reactive_compact defaults to False
- **WHEN** AgentState is created
- **THEN** has_attempted_reactive_compact is False
