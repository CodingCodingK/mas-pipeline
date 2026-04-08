## ADDED Requirements

### Requirement: run_coordinator is the unified entry point
`run_coordinator(project_id: int, user_input: str) -> CoordinatorResult` SHALL be an async function that serves as the single entry point for all user requests.

#### Scenario: Function signature
- **WHEN** run_coordinator is called with project_id and user_input
- **THEN** it SHALL return a CoordinatorResult instance

### Requirement: run_coordinator creates a WorkflowRun
`run_coordinator` SHALL create a WorkflowRun via `create_run(project_id)` before dispatching to either mode.

#### Scenario: WorkflowRun creation
- **WHEN** run_coordinator is called
- **THEN** a WorkflowRun SHALL be created with status='pending' before any mode execution begins

### Requirement: Pipeline mode routes to execute_pipeline when project has pipeline
When the Project's `pipeline` field is set and a matching YAML file exists in `pipelines/`, `run_coordinator` SHALL call `execute_pipeline()` with the run_id.

#### Scenario: Project with pipeline field set
- **WHEN** run_coordinator is called with a project whose pipeline="blog_generation"
- **AND** `pipelines/blog_generation.yaml` exists
- **THEN** it SHALL call execute_pipeline("blog_generation", run_id, project_id, user_input)
- **AND** return a CoordinatorResult with mode='pipeline'

#### Scenario: Pipeline field set but YAML not found
- **WHEN** run_coordinator is called with a project whose pipeline="nonexistent"
- **AND** no matching YAML file exists
- **THEN** it SHALL raise FileNotFoundError

### Requirement: Autonomous mode routes to coordinator_loop when no pipeline
When the Project's `pipeline` field is None or empty, `run_coordinator` SHALL create a Coordinator Agent and call `coordinator_loop()`.

#### Scenario: Project with no pipeline
- **WHEN** run_coordinator is called with a project whose pipeline is None
- **THEN** it SHALL create a Coordinator Agent (role="coordinator") and call coordinator_loop(state)
- **AND** return a CoordinatorResult with mode='autonomous'

### Requirement: CoordinatorResult contains unified output structure
`CoordinatorResult` SHALL be a dataclass with fields: run_id (str), mode (str), output (str), node_outputs (dict[str, str] | None), tasks (list[dict] | None).

#### Scenario: Pipeline mode result
- **WHEN** execute_pipeline returns a PipelineResult
- **THEN** CoordinatorResult SHALL have mode='pipeline', output=PipelineResult.final_output, node_outputs=PipelineResult.outputs, tasks=None

#### Scenario: Autonomous mode result
- **WHEN** coordinator_loop completes
- **THEN** CoordinatorResult SHALL have mode='autonomous', output=agent's final message, node_outputs=None, tasks=list of Task records for the run

### Requirement: run_coordinator finishes the WorkflowRun
After mode execution completes, `run_coordinator` SHALL call `finish_run()` with COMPLETED or FAILED status.

#### Scenario: Successful execution
- **WHEN** mode execution completes without error
- **THEN** finish_run SHALL be called with RunStatus.COMPLETED

#### Scenario: Failed execution
- **WHEN** mode execution raises an exception
- **THEN** finish_run SHALL be called with RunStatus.FAILED
- **AND** the exception SHALL be propagated
