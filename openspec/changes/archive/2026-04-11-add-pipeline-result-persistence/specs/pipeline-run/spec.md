## MODIFIED Requirements

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
