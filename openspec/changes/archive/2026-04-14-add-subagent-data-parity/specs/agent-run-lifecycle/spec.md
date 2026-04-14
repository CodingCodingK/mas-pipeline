## MODIFIED Requirements

### Requirement: complete_agent_run records successful completion
`complete_agent_run(agent_run_id, result, messages, tool_use_count, total_tokens, duration_ms)` SHALL set status to 'completed', store the result text, persist the complete `messages` list as a JSONB column, persist the three statistics columns, and update updated_at. The `messages` parameter SHALL receive the agent's full `state.messages` dict list (OpenAI format). The statistics parameters SHALL be integers; callers that don't track them MAY pass 0.

#### Scenario: Complete a running agent with full transcript
- **WHEN** complete_agent_run is called on an agent run with status='running' with result="final answer", messages=[...50 dicts...], tool_use_count=5, total_tokens=12453, duration_ms=47123
- **THEN** status SHALL be 'completed', result SHALL contain the output text, messages column SHALL contain the 50-dict list, and the three statistics columns SHALL contain 5 / 12453 / 47123

#### Scenario: Complete with empty messages permitted
- **WHEN** complete_agent_run is called with messages=[]
- **THEN** status SHALL still transition to 'completed' and messages column SHALL store an empty JSON array

### Requirement: fail_agent_run records failure
`fail_agent_run(agent_run_id, error, messages, tool_use_count, total_tokens, duration_ms)` SHALL set status to 'failed', store the error in result, persist the partial `messages` list accumulated so far, persist the three statistics columns, and update updated_at.

#### Scenario: Fail a running agent with partial transcript
- **WHEN** fail_agent_run is called on an agent run with status='running' with error="timeout", messages=[...12 dicts accumulated before failure...], tool_use_count=3, total_tokens=4200, duration_ms=15000
- **THEN** status SHALL be 'failed', result SHALL contain the error message, messages column SHALL contain the 12-dict partial list, and statistics columns SHALL contain 3 / 4200 / 15000

## ADDED Requirements

### Requirement: AgentRun stores complete transcript for post-hoc inspection
The `agent_runs` table SHALL have a `messages` column of type JSONB (default `[]`) that stores the complete `state.messages` list produced by the agent loop. This data is used for analytics and debugging; it SHALL NOT be injected back into any LLM's context.

#### Scenario: Analytics query by agent_run_id
- **WHEN** a downstream analytics component queries `SELECT messages FROM agent_runs WHERE id = ?`
- **THEN** it SHALL receive the full OpenAI-format message list that the sub-agent produced

#### Scenario: Strong isolation from main agent context
- **WHEN** a main agent (SessionRunner / pipeline orchestrator) is preparing its next LLM call
- **THEN** it SHALL NOT read `agent_runs.messages` for any reason
- **AND** the only data flowing back from a sub-agent to its caller SHALL be the `result` field (via `<task-notification>`) plus the three statistics fields

### Requirement: AgentRun stores run statistics
The `agent_runs` table SHALL have three integer columns — `tool_use_count`, `total_tokens`, `duration_ms` — each defaulting to 0. These fields SHALL be populated when `complete_agent_run` or `fail_agent_run` is called and SHALL represent the sub-agent's resource consumption over its entire loop lifetime.

#### Scenario: Completed agent exposes statistics
- **WHEN** `get_agent_run(id)` is called on a completed row
- **THEN** the returned object SHALL have `tool_use_count`, `total_tokens`, and `duration_ms` set to the values passed at completion time

#### Scenario: Legacy rows default to zero
- **WHEN** a pre-migration agent_runs row is read
- **THEN** the three statistics columns SHALL return 0 (the column default)
