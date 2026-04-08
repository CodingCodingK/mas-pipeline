## MODIFIED Requirements

### Requirement: RunStatus enum defines valid workflow run states
RunStatus(str, Enum) SHALL define: PENDING, RUNNING, COMPLETED, FAILED.

### Requirement: VALID_TRANSITIONS defines the state machine
Only the following transitions SHALL be allowed:
- PENDING → RUNNING
- RUNNING → COMPLETED
- RUNNING → FAILED

COMPLETED and FAILED are terminal states with no outgoing transitions.

### Requirement: InvalidTransitionError raised on illegal state change
`update_run_status` and `finish_run` SHALL raise InvalidTransitionError when the requested transition is not in VALID_TRANSITIONS.

#### Scenario: Illegal transition from completed
- **WHEN** update_run_status is called on a run with status='completed' to status='running'
- **THEN** it SHALL raise InvalidTransitionError

#### Scenario: Illegal transition from pending to completed
- **WHEN** update_run_status is called on a run with status='pending' to status='completed'
- **THEN** it SHALL raise InvalidTransitionError

### Requirement: create_run creates a workflow run with extended parameters
`create_run(project_id, session_id=None, pipeline=None)` SHALL insert a row into workflow_runs with a generated unique run_id, status='pending', started_at=now(), and sync to Redis. The `pipeline` field SHALL store the pipeline name when the run is associated with a pipeline execution.

#### Scenario: Create with all parameters
- **WHEN** create_run(project_id=1, session_id=5, pipeline="blog_generation") is called
- **THEN** a WorkflowRun SHALL be created with those fields set and synced to Redis

#### Scenario: Create with defaults (backward compatible)
- **WHEN** create_run(project_id=1) is called
- **THEN** session_id SHALL be None, pipeline SHALL be None

#### Scenario: Coordinator autonomous mode
- **WHEN** run_coordinator creates a run for autonomous mode
- **THEN** pipeline SHALL be None (no pipeline associated)

#### Scenario: Pipeline engine usage
- **WHEN** the Coordinator or test script creates a run with pipeline="blog_generation" and passes the run_id to execute_pipeline
- **THEN** the WorkflowRun.pipeline field SHALL match the pipeline name being executed

### Requirement: get_run retrieves a workflow run by run_id
`get_run(run_id: str)` SHALL return the WorkflowRun with matching run_id, or None if not found.

#### Scenario: Get existing run
- **WHEN** get_run is called with a valid run_id
- **THEN** it SHALL return the WorkflowRun instance

#### Scenario: Get non-existent run
- **WHEN** get_run is called with a non-existent run_id
- **THEN** it SHALL return None

### Requirement: list_runs returns all runs for a project
`list_runs(project_id: int)` SHALL return all workflow runs for the given project, ordered by id descending (newest first).

#### Scenario: List runs
- **WHEN** list_runs(project_id=1) is called
- **THEN** it SHALL return all runs with project_id=1, newest first

#### Scenario: No runs exist
- **WHEN** list_runs is called for a project with no runs
- **THEN** it SHALL return an empty list

### Requirement: update_run_status changes status with state machine validation
`update_run_status(run_id: str, status: RunStatus)` SHALL validate the transition, update the status in PG, and sync to Redis.

#### Scenario: Valid transition pending to running
- **WHEN** update_run_status(run_id, RunStatus.RUNNING) is called on a pending run
- **THEN** status SHALL be updated to 'running' in PG and Redis

### Requirement: finish_run sets terminal status and finished_at
`finish_run(run_id: str, status: RunStatus)` SHALL validate that status is COMPLETED or FAILED, perform the state transition, set finished_at=now(), and sync to Redis.

#### Scenario: Finish a running run
- **WHEN** finish_run(run_id, RunStatus.COMPLETED) is called on a running run
- **THEN** status SHALL be 'completed', finished_at SHALL be set, and Redis SHALL be updated

#### Scenario: Finish with non-terminal status
- **WHEN** finish_run(run_id, RunStatus.RUNNING) is called
- **THEN** it SHALL raise ValueError (only COMPLETED and FAILED are terminal)

### Requirement: Redis sync on every state change
Every call to create_run, update_run_status, and finish_run SHALL write to Redis Hash `workflow_run:{run_id}` with fields: project_id, pipeline, status, started_at, finished_at.
