## ADDED Requirements

### Requirement: PostgresSaver initialization
The system SHALL initialize a PostgresSaver instance using the existing database connection pool. The 4 checkpoint tables SHALL be created via `PostgresSaver.setup()` during application startup (init_db).

#### Scenario: Checkpoint tables created on startup
- **WHEN** init_db is called
- **THEN** the PostgresSaver checkpoint tables SHALL exist in the database

#### Scenario: Setup is idempotent
- **WHEN** PostgresSaver.setup() is called multiple times
- **THEN** it SHALL not fail or create duplicate tables

### Requirement: run_id maps to thread_id
The pipeline's `run_id` SHALL be used as LangGraph's `thread_id` in the checkpointer config. This links LangGraph checkpoints to our workflow_runs/agent_runs records.

#### Scenario: Checkpoint uses run_id as thread_id
- **WHEN** a pipeline executes with run_id="run-abc"
- **THEN** all LangGraph checkpoints for that execution SHALL use thread_id="run-abc"

#### Scenario: Query checkpoint by run_id
- **WHEN** get_pipeline_status("run-abc") is called
- **THEN** it SHALL query the checkpointer with thread_id="run-abc"

### Requirement: Checkpoint persists PipelineState
Each checkpoint SHALL contain the full PipelineState including all outputs collected so far. This allows inspection of intermediate results.

#### Scenario: Intermediate outputs in checkpoint
- **WHEN** node A completes with output "findings" and creates a checkpoint
- **THEN** the checkpoint SHALL contain outputs={"findings": "...content..."}

#### Scenario: Checkpoint survives process restart
- **WHEN** the process restarts after a checkpoint was saved
- **THEN** the checkpoint SHALL be retrievable from PostgreSQL

### Requirement: Checkpointer shared as singleton
The PostgresSaver instance SHALL be created once and shared across all pipeline executions. It SHALL NOT be created per-pipeline-run.

#### Scenario: Multiple pipelines share checkpointer
- **WHEN** two pipelines execute concurrently
- **THEN** both SHALL use the same PostgresSaver instance with different thread_ids
