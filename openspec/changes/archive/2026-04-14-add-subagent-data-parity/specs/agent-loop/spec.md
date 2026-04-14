## MODIFIED Requirements

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

## ADDED Requirements

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
