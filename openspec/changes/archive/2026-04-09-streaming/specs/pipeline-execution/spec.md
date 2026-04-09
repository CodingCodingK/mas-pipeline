## MODIFIED Requirements

### Requirement: Node execution via create_agent and run_agent_to_completion
Each node SHALL be executed by calling `create_agent(role, task_description, project_id, run_id, abort_signal)` followed by `run_agent_to_completion(state)`. The exit reason SHALL be read from `state.exit_reason`. The final output SHALL be extracted using `extract_final_output(state.messages)`.

#### Scenario: Node uses role file
- **WHEN** a node has role='researcher'
- **THEN** create_agent SHALL be called with role='researcher', loading agents/researcher.md

#### Scenario: Node execution returns exit reason from state
- **WHEN** run_agent_to_completion finishes
- **THEN** state.exit_reason SHALL be checked to determine success (COMPLETED) or failure (ERROR/ABORT/TOKEN_LIMIT)
