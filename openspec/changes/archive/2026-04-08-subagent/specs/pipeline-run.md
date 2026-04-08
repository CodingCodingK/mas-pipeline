## ADDED Requirements

### Requirement: PipelineRun ORM model maps to pipeline_runs table
PipelineRun model SHALL be defined in `src/models.py` with fields matching the existing `pipeline_runs` table: id, project_id, session_id, run_id(unique varchar), status, started_at, finished_at, metadata.

### Requirement: create_run inserts a minimal pipeline run record
`create_run(project_id)` SHALL insert a row into pipeline_runs with a generated unique run_id, status='running', started_at=now(), and return the PipelineRun instance.

#### Scenario: Create a run
- **WHEN** create_run(project_id=1) is called
- **THEN** a PipelineRun SHALL be created with:
  - a unique run_id string (UUID-based)
  - status='running'
  - started_at set to current timestamp
  - project_id=1

#### Scenario: Run ID uniqueness
- **WHEN** create_run is called multiple times
- **THEN** each returned PipelineRun SHALL have a distinct run_id
