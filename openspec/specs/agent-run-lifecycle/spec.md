## Purpose
Defines the lifecycle of `AgentRun` records: creation, completion, failure, and audit queries for sub-agent launches.
## Requirements
### Requirement: create_agent_run records a sub-agent launch
`create_agent_run(run_id, role, description, owner)` SHALL insert a row into the `agent_runs` table with status='running' and return an AgentRun instance.

#### Scenario: Create agent run
- **WHEN** create_agent_run is called with role='researcher' and owner='run123:researcher'
- **THEN** an AgentRun SHALL be created with status='running', role='researcher', owner set

### Requirement: complete_agent_run records successful completion
`complete_agent_run(agent_run_id, result)` SHALL set status to 'completed', store the result text, and update updated_at.

#### Scenario: Complete a running agent
- **WHEN** complete_agent_run is called on an agent run with status='running'
- **THEN** status SHALL be 'completed', result SHALL contain the output text

### Requirement: fail_agent_run records failure
`fail_agent_run(agent_run_id, error)` SHALL set status to 'failed', store the error in result, and update updated_at.

#### Scenario: Fail a running agent
- **WHEN** fail_agent_run is called on an agent run with status='running'
- **THEN** status SHALL be 'failed', result SHALL contain the error message

### Requirement: list_agent_runs and get_agent_run provide query access
`list_agent_runs(run_id)` SHALL return all agent runs for a workflow run. `get_agent_run(agent_run_id)` SHALL return a single agent run or None.

#### Scenario: List agent runs
- **WHEN** list_agent_runs is called with a valid run_id
- **THEN** it SHALL return all agent runs belonging to that workflow run

#### Scenario: Get non-existent agent run
- **WHEN** get_agent_run is called with a non-existent id
- **THEN** it SHALL return None

### Requirement: AgentRun is a pure audit record
AgentRun records SHALL NOT be used for system control flow. Sub-agent completion is signaled to the parent SessionRunner via two channels: (1) the result is persisted as a `<task-notification>` user-role message in `Conversation.messages`, and (2) the parent `SessionRunner.wakeup` event is set. The parent's main loop wakes up, re-enters `agent_loop`, and the LLM sees the new message naturally on the next turn. AgentRun rows SHALL be queried only for audit/debugging purposes.

#### Scenario: Control flow independence
- **WHEN** a SessionRunner is waiting for sub-agent completion
- **THEN** it SHALL await its `wakeup` event, NOT poll the `agent_runs` table
- **AND** the wakeup signal SHALL come from the spawn_agent background callback after it persists the notification message

#### Scenario: No queue object on state
- **WHEN** an AgentState is constructed for any session
- **THEN** it SHALL NOT contain a `notification_queue` field
- **AND** any reference to `parent_state.notification_queue` SHALL fail at import/runtime

