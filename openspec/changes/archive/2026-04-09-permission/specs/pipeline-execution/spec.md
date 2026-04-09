## MODIFIED Requirements

### Requirement: execute_pipeline function signature
`execute_pipeline(pipeline_name: str, run_id: str, project_id: int, user_input: str, permission_mode: PermissionMode = PermissionMode.NORMAL)` SHALL load the pipeline YAML, execute all nodes, and return results. The function SHALL NOT create a WorkflowRun — the caller provides a valid run_id. It SHALL fire PipelineStart hook at the beginning and PipelineEnd hook at the end. The `permission_mode` parameter SHALL default to `PermissionMode.NORMAL` (this is the only place in the codebase with a default value for permission_mode).

#### Scenario: Successful execution
- **WHEN** execute_pipeline is called with a valid pipeline_name and run_id
- **THEN** it SHALL load the pipeline, execute all nodes, and return a PipelineResult with status='completed'

#### Scenario: Pipeline YAML not found
- **WHEN** pipeline_name does not correspond to a file in the pipelines directory
- **THEN** it SHALL raise FileNotFoundError

#### Scenario: PipelineStart hook fires at beginning
- **WHEN** execute_pipeline is called
- **THEN** a PipelineStart hook event SHALL fire with payload containing pipeline_name, run_id, project_id, user_input before any node execution begins

#### Scenario: PipelineEnd hook fires on completion
- **WHEN** pipeline execution finishes (success or failure)
- **THEN** a PipelineEnd hook event SHALL fire with payload containing pipeline_name, run_id, status, error

#### Scenario: Permission mode passed to all nodes
- **WHEN** execute_pipeline is called with permission_mode=STRICT
- **THEN** every node's create_agent call SHALL receive permission_mode=STRICT

#### Scenario: Default permission mode is NORMAL
- **WHEN** execute_pipeline is called without specifying permission_mode
- **THEN** all nodes SHALL use PermissionMode.NORMAL

### Requirement: Node execution via create_agent and agent_loop
Each node SHALL be executed by calling `create_agent(role, task_description, project_id, run_id, abort_signal, permission_mode)` followed by `run_agent_to_completion(state)`. The exit reason SHALL be read from `state.exit_reason`. The final output SHALL be extracted using `extract_final_output(state.messages)`.

#### Scenario: Node uses role file
- **WHEN** a node has role='researcher'
- **THEN** create_agent SHALL be called with role='researcher', loading agents/researcher.md
