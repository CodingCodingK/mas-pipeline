## MODIFIED Requirements

### Requirement: create_run creates a workflow run with extended parameters
`create_run(project_id, session_id=None, pipeline=None)` SHALL insert a row into workflow_runs with a generated unique run_id, status='pending', and started_at=now(). The `pipeline` field SHALL store the pipeline name when the run is associated with a pipeline execution.

#### Scenario: Create with all parameters
- **WHEN** create_run(project_id=1, session_id=5, pipeline="blog_generation") is called
- **THEN** a WorkflowRun SHALL be created with those fields set

#### Scenario: Create with defaults (backward compatible)
- **WHEN** create_run(project_id=1) is called
- **THEN** session_id SHALL be None, pipeline SHALL be None

#### Scenario: Pipeline engine usage
- **WHEN** the REST trigger endpoint or a test script creates a run with pipeline="blog_generation" and passes the run_id to execute_pipeline
- **THEN** the WorkflowRun.pipeline field SHALL match the pipeline name being executed

### Requirement: update_run_status changes status with state machine validation

`update_run_status(run_id: str, status: RunStatus, *, result_payload: dict | None = None)` SHALL validate the transition and update the status in PG. When `result_payload` is provided, it SHALL be shallow-merged into `WorkflowRun.metadata_` inside the same database session as the status transition (single transaction). Keys already present in `metadata_` that are not in `result_payload` SHALL be preserved.

The merge SHALL be performed by reassigning a fresh dict (`run.metadata_ = {**existing, **payload}`), not by in-place mutation, so SQLAlchemy flushes the JSONB column.

#### Scenario: Valid transition pending to running

- **WHEN** update_run_status(run_id, RunStatus.RUNNING) is called on a pending run
- **THEN** status SHALL be updated to 'running' in PG

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

`finish_run(run_id: str, status: RunStatus, *, result_payload: dict | None = None)` SHALL validate that status is COMPLETED or FAILED, perform the state transition, and set finished_at=now(). When `result_payload` is provided, it SHALL be shallow-merged into `WorkflowRun.metadata_` inside the same database session as the status transition and finished_at write — a single transaction.

#### Scenario: Finish a running run

- **WHEN** finish_run(run_id, RunStatus.COMPLETED) is called on a running run
- **THEN** status SHALL be 'completed' AND finished_at SHALL be set

#### Scenario: Finish with non-terminal status

- **WHEN** finish_run(run_id, RunStatus.RUNNING) is called
- **THEN** it SHALL raise ValueError (only COMPLETED and FAILED are terminal)

#### Scenario: Finish with pipeline result payload

- **WHEN** finish_run(run_id, RunStatus.COMPLETED, result_payload={"final_output": "# Report", "outputs": {"writer": "# Report"}, "failed_node": None, "error": None, "paused_at": None}) is called on a running run
- **THEN** status SHALL be 'completed' AND finished_at SHALL be set AND metadata_['final_output'] SHALL equal '# Report' AND metadata_['outputs'] SHALL equal {"writer": "# Report"}

#### Scenario: Finish failure path persists error and empty final_output

- **WHEN** finish_run(run_id, RunStatus.FAILED, result_payload={"final_output": "", "outputs": {}, "failed_node": None, "error": "embedding API timeout", "paused_at": None}) is called on a running run
- **THEN** status SHALL be 'failed' AND metadata_['final_output'] SHALL equal '' (never None) AND metadata_['error'] SHALL equal 'embedding API timeout'

## REMOVED Requirements

### Requirement: Redis sync on every state change
**Reason**: Dead cache. The write path (`_sync_to_redis`) was implemented in the 2026-04-08 `workflow-run` change but no reader was ever added. The 2026-04-14 Redis audit confirmed zero `hget`/`hgetall` references across `src/`. The Hash had no TTL, so keys grew 1:1 with `workflow_runs` rows — a linear leak. Path A (remove the write path) was chosen over Path B (add a TTL) because a self-expiring cache with no readers is still unused code.

**Migration**: None required at runtime — PG is and always has been the source of truth for run state. After deploy, one-time operator sweep to flush orphan Redis keys:
```
redis-cli --scan --pattern 'workflow_run:*' | xargs -r redis-cli DEL
```
Any future caller that truly needs a hot-path cache for run status should propose a new spec change with a documented reader surface and TTL from day one.
