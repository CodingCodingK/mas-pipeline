# run-ops-controls Specification

## Purpose
TBD - created by archiving change improve-run-observability-and-ops. Update Purpose after archive.
## Requirements
### Requirement: Pause endpoint with soft-abort semantics

The system SHALL expose `POST /api/runs/{run_id}/pause` that requests a pause on a running pipeline. The endpoint SHALL set an `abort_signal` on the currently executing node's `AgentState` and SHALL flip `workflow_runs.status` to `paused`. The currently in-flight LLM call SHALL be allowed to complete before the abort takes effect — mid-call interruption is NOT supported.

The endpoint SHALL return HTTP 200 with `{status: "pause_requested", run_id, paused_at_node?}` on a run that is currently in `status="running"`. It SHALL return HTTP 409 with `{detail: "run is not running"}` if the run is already `paused`, `completed`, `failed`, or `cancelled`. It SHALL return HTTP 404 if `run_id` does not exist.

The endpoint SHALL be idempotent with respect to a `pause_requested` state: calling it twice on the same running run SHALL return the same 200 response without creating a duplicate abort signal.

#### Scenario: Pause on a running pipeline returns 200 and sets abort

- **GIVEN** a run `run_abc` with `workflow_runs.status="running"` and an active agent executing
- **WHEN** a client issues `POST /api/runs/run_abc/pause`
- **THEN** the response SHALL be HTTP 200 with `status="pause_requested"`
- **AND** the active agent's `AgentState.abort_signal` SHALL be set
- **AND** `workflow_runs.status` SHALL be `"paused"` (the DB write happens when the loop yields)

#### Scenario: Pause on an already paused run returns 409

- **GIVEN** a run with `status="paused"`
- **WHEN** a client issues `POST /api/runs/{run_id}/pause`
- **THEN** the response SHALL be HTTP 409

#### Scenario: Pause on a completed run returns 409

- **GIVEN** a run with `status="completed"`
- **WHEN** a client issues `POST /api/runs/{run_id}/pause`
- **THEN** the response SHALL be HTTP 409

### Requirement: Cancel endpoint with sub-agent cascade

The system SHALL expose `POST /api/runs/{run_id}/cancel` that terminates a running or paused pipeline. The endpoint SHALL set `abort_signal` on the currently executing node's `AgentState`, flip `workflow_runs.status` to `cancelled`, and cascade cancellation to any running sub-agent tasks spawned by nodes in this run.

The cascade SHALL be implemented by walking the child-task registry maintained by `spawn_agent` and setting abort on each descendant's `AgentState`. Sub-agent tasks whose parent run_id matches the cancelled run SHALL receive the abort signal regardless of depth.

The endpoint SHALL return HTTP 200 with `{status: "cancelled", run_id, cancelled_node_count}` on success. It SHALL return HTTP 409 if the run is already `completed`, `failed`, or `cancelled`. It SHALL return HTTP 404 if `run_id` does not exist.

Cancelled runs SHALL NOT be resumable — a subsequent `POST /api/runs/{run_id}/resume` SHALL return HTTP 409.

#### Scenario: Cancel on a running pipeline with spawned sub-agents

- **GIVEN** a run with one top-level node executing and two sub-agent tasks spawned by that node
- **WHEN** a client issues `POST /api/runs/{run_id}/cancel`
- **THEN** the response SHALL be HTTP 200 with `cancelled_node_count=3`
- **AND** the top-level node's `AgentState.abort_signal` SHALL be set
- **AND** both sub-agent tasks' `AgentState.abort_signal` SHALL be set
- **AND** `workflow_runs.status` SHALL eventually be `"cancelled"`

#### Scenario: Cancel on a paused pipeline

- **GIVEN** a run with `status="paused"` at an interrupt
- **WHEN** a client issues `POST /api/runs/{run_id}/cancel`
- **THEN** the response SHALL be HTTP 200
- **AND** `workflow_runs.status` SHALL transition from `paused` to `cancelled`

#### Scenario: Resume after cancel is rejected

- **GIVEN** a run was cancelled via `POST /api/runs/{run_id}/cancel`
- **WHEN** a client issues `POST /api/runs/{run_id}/resume` with `{action: "approve"}`
- **THEN** the response SHALL be HTTP 409

### Requirement: REST resume endpoint body contract

The system SHALL expose `POST /api/runs/{run_id}/resume` (which already exists as of this change) with a tightened request body contract. The endpoint SHALL accept two body shapes:

1. **Structured form (preferred):** `{value: {action: "approve"|"reject"|"edit", feedback?: string, edited?: string}}` where the inner object carries the three-way review action and any user-provided text. `value.action` is required; `value.feedback` is a string used by the reject path; `value.edited` is a string used by the edit path.
2. **Legacy bare form (backward-compat):** `{value: <string or null>}` where `value` is interpreted as reject-feedback (matching the pre-change behavior). This form SHALL remain accepted so CLI callers and existing tests do not break.

Body validation for the structured form:
- `action="approve"`: any `feedback` or `edited` fields SHALL be dropped at the API layer before forwarding to `resume_pipeline`.
- `action="reject"`: `feedback` MAY be present or absent; when absent, the empty string SHALL be forwarded.
- `action="edit"`: `edited` SHALL be a non-empty string. If missing or empty, the endpoint SHALL return HTTP 422.

The endpoint SHALL call `src.engine.pipeline.resume_pipeline` with the (possibly cleaned) structured dict as the `feedback` argument. The existing `src/engine/graph.py::interrupt_fn` already dispatches the dict correctly into the three-way branch.

The endpoint SHALL return HTTP 202 with `{status: "resumed", run_id}` on success. It SHALL return HTTP 409 if the run is not in `status="paused"`. It SHALL return HTTP 404 if `run_id` does not exist.

The existing `/resume <run_id>` bus command path (processed by `src/bus/gateway.py`) SHALL remain unchanged and continues to call the same underlying `resume_pipeline` function. The REST endpoint and the bus command are two independent entry points into the same engine-level resume operation.

#### Scenario: Approve forwards empty feedback and returns 200

- **GIVEN** a run paused at an `editor_interrupt` node
- **WHEN** a client issues `POST /api/runs/{run_id}/resume` with `{action: "approve"}`
- **THEN** the response SHALL be HTTP 200
- **AND** `resume_pipeline` SHALL be called with `feedback=""` (no downstream feedback)

#### Scenario: Reject forwards feedback and returns 200

- **GIVEN** a run paused at `editor_interrupt`
- **WHEN** a client issues `POST /api/runs/{run_id}/resume` with `{action: "reject", feedback: "rewrite section 2"}`
- **THEN** the response SHALL be HTTP 200
- **AND** `resume_pipeline` SHALL be called with the action and feedback in the shape the existing graph handler expects

#### Scenario: Edit without edited field returns 422

- **GIVEN** a run paused at an interrupt
- **WHEN** a client issues `POST /api/runs/{run_id}/resume` with `{action: "edit"}` and no `edited` field
- **THEN** the response SHALL be HTTP 422

#### Scenario: Resume on a non-paused run returns 409

- **GIVEN** a run with `status="running"` (not paused)
- **WHEN** a client issues `POST /api/runs/{run_id}/resume` with `{action: "approve"}`
- **THEN** the response SHALL be HTTP 409

### Requirement: Pause and cancel are surfaced as header controls in the web UI

The run detail page in the web UI SHALL render two buttons in the page header: "Pause" and "Cancel". Pause SHALL be visible and enabled only when the run is in `status="running"`. Cancel SHALL be visible and enabled when the run is in `status="running"` or `status="paused"`. Both buttons SHALL invoke the corresponding REST endpoint and SHALL update the page state based on the response.

Cancel SHALL require a confirmation dialog ("Cancel this run? This cannot be undone.") before issuing the request. Pause SHALL NOT require confirmation.

While a pause is pending (between click and backend state change), the pause button SHALL be replaced with a disabled "Pausing..." indicator. Once the SSE stream or a poll confirms `status="paused"`, the header SHALL show the paused state and offer the approve/reject/edit controls appropriate to the interrupt.

#### Scenario: Pause button fires pause endpoint

- **GIVEN** the run detail page is showing a running pipeline
- **WHEN** the user clicks "Pause"
- **THEN** a `POST /api/runs/{run_id}/pause` request SHALL be issued
- **AND** the button SHALL be replaced with a disabled "Pausing..." indicator until the status changes

#### Scenario: Cancel requires confirmation

- **GIVEN** the run detail page is showing a running pipeline
- **WHEN** the user clicks "Cancel"
- **THEN** a confirmation dialog SHALL appear
- **AND** the backend request SHALL be issued only after confirmation

#### Scenario: Paused state offers approve/reject/edit buttons

- **GIVEN** the run detail page is showing a run that just transitioned to `paused` at an interrupt
- **WHEN** the paused state is rendered
- **THEN** the header SHALL display three buttons: Approve, Reject, Edit
- **AND** the Approve button SHALL NOT have an associated comment input field

