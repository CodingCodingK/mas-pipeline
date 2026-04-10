## REMOVED Requirements

### Requirement: Pipeline mode routes to execute_pipeline when project has pipeline
**Reason**: Pipeline routing is now the caller's responsibility — `run_coordinator` no longer checks `Project.pipeline` or dispatches to `execute_pipeline`.
**Migration**: Callers (CLI, API, test scripts) should check `Project.pipeline` themselves and call `execute_pipeline()` directly when set.

### Requirement: Autonomous mode routes to coordinator_loop when no pipeline
**Reason**: `run_coordinator` is now unconditionally autonomous; the "routing" framing no longer applies.
**Migration**: Replaced by "run_coordinator only handles autonomous mode" requirement.

## MODIFIED Requirements

### Requirement: run_coordinator is the unified entry point
`run_coordinator(project_id: int, user_input: str) -> CoordinatorResult` SHALL be an async function that runs the autonomous coordinator loop. It SHALL NOT check `Project.pipeline` or call `execute_pipeline`. Pipeline routing is the caller's responsibility.

#### Scenario: Function signature
- **WHEN** run_coordinator is called with project_id and user_input
- **THEN** it SHALL return a CoordinatorResult instance

#### Scenario: run_coordinator runs autonomous mode unconditionally
- **WHEN** run_coordinator is called
- **THEN** it SHALL create a WorkflowRun and start coordinator_loop, regardless of Project.pipeline

#### Scenario: run_coordinator does not call execute_pipeline
- **WHEN** run_coordinator is called for a project that has a pipeline configured
- **THEN** it SHALL NOT call execute_pipeline (caller should have routed to execute_pipeline directly)

### Requirement: CoordinatorResult contains unified output structure
`CoordinatorResult` SHALL be a dataclass with fields relevant to autonomous mode only: `run_id` (str), `mode` (always `'autonomous'`), `output` (str), `tasks` (list[dict] | None). It SHALL NOT contain `node_outputs` or support `mode='pipeline'`.

#### Scenario: Autonomous mode result
- **WHEN** coordinator_loop completes
- **THEN** CoordinatorResult SHALL have mode='autonomous', output=agent's final message, tasks=list of Task records for the run

#### Scenario: No pipeline-related fields
- **WHEN** CoordinatorResult is returned
- **THEN** it SHALL NOT contain `node_outputs` and `mode` SHALL NOT be `'pipeline'`

## ADDED Requirements

### Requirement: Caller performs pipeline routing
The caller (CLI, API, test scripts) SHALL check `Project.pipeline` and route accordingly: if pipeline is set, call `execute_pipeline()` directly; if not, call `run_coordinator()`.

#### Scenario: Caller routes to pipeline
- **WHEN** a project has pipeline="blog_generation"
- **THEN** the caller SHALL call execute_pipeline("blog_generation", ...) directly

#### Scenario: Caller routes to coordinator
- **WHEN** a project has no pipeline (pipeline is None or empty)
- **THEN** the caller SHALL call run_coordinator(project_id, user_input)
