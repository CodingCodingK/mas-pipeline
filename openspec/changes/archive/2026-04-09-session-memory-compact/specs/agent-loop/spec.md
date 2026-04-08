## MODIFIED Requirements

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
