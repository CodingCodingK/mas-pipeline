## MODIFIED Requirements

### Requirement: coordinator_loop wraps agent_loop with outer do-while
`coordinator_loop(state: AgentState)` SHALL be an async generator that yields `StreamEvent`. It SHALL wrap agent_loop in an outer loop: yield all events from agent_loop, then check running_agent_count. It SHALL set `state.exit_reason` before ending.

#### Scenario: No running agents after agent_loop
- **WHEN** agent_loop ends
- **AND** state.running_agent_count is 0
- **THEN** coordinator_loop SHALL set state.exit_reason and end the generator

#### Scenario: Running agents still active
- **WHEN** agent_loop ends
- **AND** state.running_agent_count > 0
- **THEN** coordinator_loop SHALL await state.notification_queue.get()

### Requirement: coordinator_loop re-enters agent_loop after notification injection
After injecting notifications, coordinator_loop SHALL iterate agent_loop(state) again, yielding all events from the re-entered loop.

#### Scenario: Re-entry yields events from new agent_loop iteration
- **WHEN** notifications have been injected and agent_loop is re-entered
- **THEN** coordinator_loop SHALL yield all StreamEvent from the new agent_loop iteration

### Requirement: run_coordinator_to_completion helper
`run_coordinator_to_completion(state: AgentState) -> ExitReason` SHALL consume all events from coordinator_loop(state) silently and return state.exit_reason. This is the migration path for callers that do not need streaming.

#### Scenario: Returns ExitReason after completion
- **WHEN** run_coordinator_to_completion is called
- **THEN** it SHALL iterate all events from coordinator_loop and return state.exit_reason
