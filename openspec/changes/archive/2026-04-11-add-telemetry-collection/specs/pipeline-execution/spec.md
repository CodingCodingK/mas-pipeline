## ADDED Requirements

### Requirement: Pipeline execution emits pipeline_event at run and node boundaries
The pipeline engine SHALL emit `pipeline_event` telemetry at the following transitions:

- `pipeline_start` — when a pipeline run begins executing
- `node_start` — when a pipeline node starts executing
- `node_end` — when a pipeline node completes successfully, with `duration_ms`
- `node_failed` — when a pipeline node fails, with `duration_ms` and `error_msg`
- `paused` — when a pipeline enters an interrupt/pause state (HITL review)
- `resumed` — when a paused pipeline resumes execution
- `pipeline_end` — when a pipeline run completes (success or terminal failure)

The pipeline engine SHALL also set `current_run_id` contextvar on the telemetry module at `pipeline_start` and reset it at `pipeline_end`, so that `llm_call` / `tool_call` / `agent_turn` events emitted by agents running inside pipeline nodes automatically carry the correct `run_id` field.

Emission SHALL use the existing telemetry collector (same instance registered in FastAPI lifespan), not introduce a new event channel.

#### Scenario: Successful pipeline run emits full sequence
- **WHEN** a blog generation pipeline runs 3 nodes to completion
- **THEN** the emitted `pipeline_event` sequence SHALL be: `pipeline_start`, `node_start`(×3), `node_end`(×3), `pipeline_end` — in that relative order

#### Scenario: Pipeline run_id propagates to nested agent events
- **WHEN** a pipeline node invokes an agent that makes an LLM call
- **THEN** the `llm_call` event SHALL have `run_id` set to the pipeline's run_id (from the contextvar)

#### Scenario: Node failure emits node_failed and pipeline_end
- **WHEN** a pipeline node raises an unhandled exception
- **THEN** a `pipeline_event` with `pipeline_event_type='node_failed'` SHALL be emitted with `error_msg`
- **AND** a `pipeline_event` with `pipeline_event_type='pipeline_end'` SHALL be emitted
- **AND** an `error` event with `source='pipeline'` SHALL also be emitted

#### Scenario: Pause and resume both emit events
- **WHEN** a pipeline hits a HITL interrupt and later resumes
- **THEN** a `paused` event SHALL be emitted at the interrupt and a `resumed` event SHALL be emitted when `resume_pipeline` is called
