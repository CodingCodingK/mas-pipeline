## MODIFIED Requirements

### Requirement: create_run creates a workflow run with extended parameters
`create_run(project_id, session_id=None, pipeline=None)` SHALL insert a row into workflow_runs with a generated unique run_id, status='pending', started_at=now(), and sync to Redis. The `pipeline` field SHALL store the pipeline name when the run is associated with a pipeline execution.

#### Scenario: Create with all parameters
- **WHEN** create_run(project_id=1, session_id=5, pipeline="blog_generation") is called
- **THEN** a WorkflowRun SHALL be created with those fields set and synced to Redis

#### Scenario: Create with defaults (backward compatible)
- **WHEN** create_run(project_id=1) is called
- **THEN** session_id SHALL be None, pipeline SHALL be None

#### Scenario: Pipeline engine usage
- **WHEN** the Coordinator or test script creates a run with pipeline="blog_generation" and passes the run_id to execute_pipeline
- **THEN** the WorkflowRun.pipeline field SHALL match the pipeline name being executed
