## Purpose
Defines `WorkflowRun` lifecycle: status enum, state transitions, and abort signaling.
## Requirements
### Requirement: RunStatus enum defines valid workflow run states
RunStatus(str, Enum) SHALL define: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED.

#### Scenario: Enum members
- **WHEN** RunStatus is imported
- **THEN** it SHALL expose PENDING, RUNNING, COMPLETED, FAILED, CANCELLED as string values

### Requirement: VALID_TRANSITIONS defines the state machine
Only the following transitions SHALL be allowed:
- PENDING → RUNNING
- PENDING → CANCELLED
- RUNNING → COMPLETED
- RUNNING → FAILED
- RUNNING → CANCELLED
- RUNNING → PAUSED (when an interrupt node pauses execution)
- PAUSED → RUNNING (resume)
- PAUSED → CANCELLED

COMPLETED, FAILED, and CANCELLED are terminal states with no outgoing transitions.

#### Scenario: Cancel allowed from running
- **WHEN** update_run_status is called on a run with status='running' to status='cancelled'
- **THEN** the transition SHALL succeed and the run SHALL be in cancelled state

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

#### Scenario: Pipeline engine usage
- **WHEN** the REST trigger endpoint or a test script creates a run with pipeline="blog_generation" and passes the run_id to execute_pipeline
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

`update_run_status(run_id: str, status: RunStatus, *, result_payload: dict | None = None)` SHALL validate the transition, update the status in PG, and sync to Redis. When `result_payload` is provided, it SHALL be shallow-merged into `WorkflowRun.metadata_` inside the same database session as the status transition (single transaction). Keys already present in `metadata_` that are not in `result_payload` SHALL be preserved.

The merge SHALL be performed by reassigning a fresh dict (`run.metadata_ = {**existing, **payload}`), not by in-place mutation, so SQLAlchemy flushes the JSONB column.

#### Scenario: Valid transition pending to running

- **WHEN** update_run_status(run_id, RunStatus.RUNNING) is called on a pending run
- **THEN** status SHALL be updated to 'running' in PG and Redis

#### Scenario: Transition with result_payload merges into metadata

- **WHEN** update_run_status(run_id, RunStatus.PAUSED, result_payload={"paused_at": "node_b", "outputs": {"a": "hi"}}) is called on a running run
- **THEN** status SHALL be 'paused' AND metadata_['paused_at'] SHALL equal 'node_b' AND metadata_['outputs'] SHALL equal {"a": "hi"}

#### Scenario: result_payload defaults to None (backward compat)

- **WHEN** update_run_status(run_id, RunStatus.RUNNING) is called without a result_payload kwarg
- **THEN** metadata_ SHALL be unchanged from its prior value

#### Scenario: Merge preserves unrelated metadata keys

- **GIVEN** a run with metadata_ = {"trace_id": "abc-123"}
- **WHEN** update_run_status(run_id, RunStatus.PAUSED, result_payload={"paused_at": "n1"}) is called
- **THEN** metadata_ SHALL equal {"trace_id": "abc-123", "paused_at": "n1"}

### Requirement: finish_run sets terminal status and finished_at

`finish_run(run_id: str, status: RunStatus, *, result_payload: dict | None = None)` SHALL validate that status is COMPLETED or FAILED, perform the state transition, set finished_at=now(), and sync to Redis. When `result_payload` is provided, it SHALL be shallow-merged into `WorkflowRun.metadata_` inside the same database session as the status transition and finished_at write — a single transaction.

#### Scenario: Finish a running run

- **WHEN** finish_run(run_id, RunStatus.COMPLETED) is called on a running run
- **THEN** status SHALL be 'completed', finished_at SHALL be set, and Redis SHALL be updated

#### Scenario: Finish with non-terminal status

- **WHEN** finish_run(run_id, RunStatus.RUNNING) is called
- **THEN** it SHALL raise ValueError (only COMPLETED and FAILED are terminal)

#### Scenario: Finish with pipeline result payload

- **WHEN** finish_run(run_id, RunStatus.COMPLETED, result_payload={"final_output": "# Report", "outputs": {"writer": "# Report"}, "failed_node": None, "error": None, "paused_at": None}) is called on a running run
- **THEN** status SHALL be 'completed' AND finished_at SHALL be set AND metadata_['final_output'] SHALL equal '# Report' AND metadata_['outputs'] SHALL equal {"writer": "# Report"}

#### Scenario: Finish failure path persists error and empty final_output

- **WHEN** finish_run(run_id, RunStatus.FAILED, result_payload={"final_output": "", "outputs": {}, "failed_node": None, "error": "embedding API timeout", "paused_at": None}) is called on a running run
- **THEN** status SHALL be 'failed' AND metadata_['final_output'] SHALL equal '' (never None) AND metadata_['error'] SHALL equal 'embedding API timeout'

### Requirement: Redis sync on every state change

Every call to create_run, update_run_status, and finish_run SHALL write to Redis Hash `workflow_run:{run_id}` with fields: project_id, pipeline, status, started_at, finished_at. The `result_payload` SHALL NOT be written to Redis — it is a PG-only JSONB payload consumed on cold paths (export, telemetry tree reconstruction) and would bloat hot-path lookups.

#### Scenario: Status change syncs to Redis

- **WHEN** update_run_status is called for a run
- **THEN** the matching Redis Hash `workflow_run:{run_id}` SHALL reflect the new status field

#### Scenario: result_payload is not mirrored to Redis

- **WHEN** finish_run(run_id, RunStatus.COMPLETED, result_payload={"final_output": "hello"}) is called
- **THEN** the Redis Hash `workflow_run:{run_id}` SHALL NOT contain a 'final_output' field

### Requirement: Pipeline run detail page exposes per-node agent run drawer
The `RunDetailPage` SHALL expose a per-node UI affordance (clickable row, button, or DAG node click) that opens the shared `AgentRunDetailDrawer` component for the agent_run associated with that node. The drawer SHALL fetch `GET /api/agent-runs/{id}` and render the same information as the chat variant (statistics header, description, transcript, result). This is a **frontend-only** addition; pipeline execution semantics SHALL NOT change.

The agent_run id for a given node SHALL be looked up via the existing `GET /api/runs/{run_id}/agent-runs` list response (matching by `role` or `owner`). This lookup SHALL be performed lazily when the user opens the drawer for a node, not on page load.

#### Scenario: Click node in pipeline run detail
- **WHEN** a user clicks a node (row or graph node) in `RunDetailPage`
- **THEN** the page SHALL find the matching `agent_run_id` from the list of agent runs for that workflow run
- **AND** SHALL open `AgentRunDetailDrawer` with that id
- **AND** the drawer SHALL display the agent's full transcript and statistics

#### Scenario: Node with no agent run (e.g., interrupt node)
- **WHEN** a user clicks a node whose type does not correspond to an agent run (e.g., a pure interrupt node)
- **THEN** the drawer SHALL NOT open
- **AND** the node row SHALL NOT appear clickable (or SHALL display a disabled state)

#### Scenario: Drawer shared across chat and pipeline contexts
- **WHEN** `AgentRunDetailDrawer` is used in either the chat page or the pipeline run detail page
- **THEN** the same component SHALL be used with the same props contract (`agentRunId`, `onClose`)
- **AND** the REST endpoint and response schema SHALL be identical for both contexts

#### Scenario: Statistics visible without opening drawer
- **WHEN** the per-node list view is rendered
- **THEN** each row representing an agent run SHALL display inline badges showing `tool_use_count`, `total_tokens`, `duration_ms` from the list response (these three fields remain in the list endpoint even though `messages` is excluded)

