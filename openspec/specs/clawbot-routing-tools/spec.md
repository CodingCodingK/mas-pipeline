# clawbot-routing-tools Specification

## Purpose
TBD - created by archiving change add-clawbot-third-party-chat. Update Purpose after archive.
## Requirements
### Requirement: Meta-capability tools
The system SHALL provide `list_projects`, `get_project_info(project_id)`, and `get_run_progress(run_id)` tools registered exclusively to the clawbot role. These tools take explicit parameters and MUST NOT read `tool_context.project_id`.

#### Scenario: List projects
- **WHEN** clawbot calls `list_projects` with no arguments
- **THEN** the tool returns id, name, pipeline, and status for every project in the database

#### Scenario: Get project info
- **WHEN** clawbot calls `get_project_info(project_id=42)`
- **THEN** the tool returns name, description, default pipeline, and document count for project 42, or an error if the project does not exist

#### Scenario: Get run progress
- **WHEN** clawbot calls `get_run_progress(run_id="run-123")`
- **THEN** the tool returns the current status, current node, started_at, and (if finished) finished_at for the run

### Requirement: Self-answer tools
The system SHALL provide `search_project_docs(project_id, query)` as a wrapper around the existing vector retrieval, taking project_id as an explicit parameter rather than via `tool_context`. The legacy `search_docs` tool MUST remain unchanged for pipeline/assistant use.

#### Scenario: Explicit project param
- **WHEN** clawbot calls `search_project_docs(project_id=7, query="...")`
- **THEN** the tool retrieves chunks scoped to project 7 without consulting `tool_context`

#### Scenario: Legacy tool untouched
- **WHEN** any pipeline node or assistant agent calls `search_docs`
- **THEN** the existing implementation reading `tool_context.project_id` continues to work unchanged

### Requirement: Run dispatch tool with two-phase commit
The system SHALL provide `start_project_run(project_id, inputs, pipeline=None)` that does NOT execute the pipeline directly. Instead it stores a `PendingRun{project_id, inputs, pipeline}` slot in the clawbot session state and returns a "待确认" message. When `pipeline` is omitted, the tool resolves the project's default `pipeline` field.

#### Scenario: Pending slot stored
- **WHEN** clawbot calls `start_project_run(project_id=3, inputs={...})`
- **THEN** the tool writes `PendingRun(project_id=3, inputs={...}, pipeline=<project default>)` into the session pending slot, schedules a 90-second TTL cleanup, and returns a confirmation-needed result

#### Scenario: Default pipeline resolution
- **WHEN** the call omits `pipeline` and the project has `pipeline="blog_generation"`
- **THEN** the pending slot stores `pipeline="blog_generation"`

#### Scenario: Single-slot overwrite
- **WHEN** a second `start_project_run` is called while a pending slot already exists
- **THEN** the new call overwrites the old slot and the response indicates the prior pending run was replaced

#### Scenario: Same-turn double call rejected
- **WHEN** the LLM emits two `start_project_run` calls in the same turn
- **THEN** the tool layer keeps only the first and returns `success=False` for the second

### Requirement: Confirm and cancel tools
The system SHALL provide `confirm_pending_run()` and `cancel_pending_run()` tools that operate on the session's pending slot. `confirm_pending_run` triggers `asyncio.create_task(execute_pipeline(...))` fire-and-forget and registers a `ChatProgressReporter`. `cancel_pending_run` clears the slot.

#### Scenario: Confirm launches pipeline
- **WHEN** clawbot calls `confirm_pending_run()` and a pending slot exists
- **THEN** the tool clears the slot, spawns an `asyncio.Task` running the pipeline with the pending parameters, registers a reporter under the new run_id in the Gateway-level registry, and returns the run_id

#### Scenario: Confirm with no pending
- **WHEN** clawbot calls `confirm_pending_run()` and no pending slot exists
- **THEN** the tool returns `success=False` with a "no pending run" message

#### Scenario: Cancel clears slot
- **WHEN** clawbot calls `cancel_pending_run()`
- **THEN** the pending slot is cleared and a confirmation message is returned

### Requirement: ClawBot tools never injected via tool_context
The system SHALL ensure all seven clawbot tools declare every required field as an explicit JSONSchema parameter and the clawbot tool execution path MUST NOT mutate `tool_context.project_id`.

#### Scenario: Schema declares project_id
- **WHEN** any clawbot tool that needs a project is invoked
- **THEN** its schema includes `project_id` as a required integer parameter

