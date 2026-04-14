## MODIFIED Requirements

### Requirement: Run detail page streams events via SSE

`web/src/pages/RunDetailPage.tsx` SHALL render a pipeline run as a DAG using `@xyflow/react` + `@dagrejs/dagre` (both already declared in `web/package.json`). On mount, the page SHALL fetch `GET /api/runs/{run_id}/graph` to build the initial DAG and SHALL open an SSE connection to stream live events from `POST /api/projects/:id/pipelines/:name/runs?stream=true` (when entered with a pending trigger) or from the existing run-event stream endpoint (when viewing an in-flight or completed run).

The DAG SHALL be the primary surface of the page. Node background colors SHALL reflect node status per the mapping defined in the `run-dag-visualization` capability (idle gray, running blue pulse, completed green, failed red, paused amber, cancelled dark gray, skipped light gray dashed). SSE events that change a node's status SHALL patch the DAG in place without refetching `/graph`.

Clicking a node SHALL open a collapsible drawer showing the event/turn log scoped to that node. The drawer is the ONLY surface on the run detail page where the legacy linear event log is rendered; the page SHALL NOT display a flat scrolling log as its main view.

The page SHALL render two operator buttons in the header: **Pause** (visible when status is `running`) and **Cancel** (visible when status is `running` or `paused`). The Pause button SHALL call `POST /api/runs/{run_id}/pause`. The Cancel button SHALL call `POST /api/runs/{run_id}/cancel` after a confirmation dialog. While a pause is in flight, the Pause button SHALL show a disabled "Pausing..." indicator until the backend confirms the paused state via SSE or a status poll.

When the run is `paused` at an interrupt, the header SHALL render three review buttons — **Approve**, **Reject**, **Edit** — that call `POST /api/runs/{run_id}/resume` with the appropriate `action` field. The Approve button SHALL NOT have an associated comment input field; its click SHALL immediately issue `{action: "approve"}` with no body beyond that. The Reject button SHALL open a feedback textarea before issuing `{action: "reject", feedback: "..."}`. The Edit button SHALL open an editor initialized with the current interrupted output and SHALL issue `{action: "edit", edited: "..."}` on save.

The page SHALL display the run's final status when the SSE stream closes with `pipeline_end` or `pipeline_failed`, and SHALL also support loading a completed run by fetching `GET /api/runs/:runId` on mount when no pending trigger is present.

#### Scenario: Streams live events

- **GIVEN** a running pipeline emits three events then closes
- **WHEN** the page streams the run
- **THEN** the DAG SHALL reflect each event by updating the corresponding node's status color
- **AND** the final status SHALL be "completed"

#### Scenario: DAG is primary surface, linear log is not on main view

- **GIVEN** the run detail page is rendered for any run
- **WHEN** the page mounts
- **THEN** the main content area SHALL render a DAG
- **AND** SHALL NOT render a flat scrolling event log as its main view

#### Scenario: Node click opens drawer with scoped log

- **GIVEN** the run detail page is showing a DAG with a `writer` node
- **WHEN** the user clicks the `writer` node
- **THEN** a drawer SHALL slide in containing events and turns scoped to the `writer` node

#### Scenario: Pause button calls pause endpoint

- **GIVEN** the run detail page is showing a pipeline in `status="running"`
- **WHEN** the user clicks the Pause header button
- **THEN** a `POST /api/runs/{run_id}/pause` request SHALL be issued
- **AND** the button SHALL show a disabled "Pausing..." indicator until the status changes

#### Scenario: Cancel button confirms then calls cancel endpoint

- **GIVEN** the run detail page is showing a pipeline in `status="running"`
- **WHEN** the user clicks the Cancel header button
- **THEN** a confirmation dialog SHALL appear
- **AND** after confirmation, a `POST /api/runs/{run_id}/cancel` request SHALL be issued

#### Scenario: Approve button calls resume endpoint with no comment field

- **GIVEN** the run detail page is showing a pipeline in `status="paused"` at an interrupt
- **WHEN** the user clicks the Approve button
- **THEN** no comment input field SHALL be presented to the user
- **AND** a `POST /api/runs/{run_id}/resume` request with body `{action: "approve"}` SHALL be issued

#### Scenario: Reject button opens feedback textarea then calls resume endpoint

- **GIVEN** the run detail page is showing a pipeline in `status="paused"` at an interrupt
- **WHEN** the user clicks the Reject button
- **THEN** a feedback textarea SHALL be shown
- **AND** after the user enters feedback and submits, a `POST /api/runs/{run_id}/resume` request with body `{action: "reject", feedback: "<entered text>"}` SHALL be issued

#### Scenario: Edit button opens editor initialized with current output then calls resume endpoint

- **GIVEN** the run detail page is showing a pipeline in `status="paused"` at an interrupt with the paused node's output preview available
- **WHEN** the user clicks the Edit button
- **THEN** an editor SHALL be shown pre-populated with the current interrupted output
- **AND** after the user edits and saves, a `POST /api/runs/{run_id}/resume` request with body `{action: "edit", edited: "<edited text>"}` SHALL be issued

#### Scenario: UI continues to receive run events after resume (8.3 silent-click fix)

- **GIVEN** the run detail page is showing a pipeline paused at an interrupt with an active SSE subscription
- **WHEN** the user clicks Approve and `POST /api/runs/{run_id}/resume` succeeds
- **THEN** the SSE subscription SHALL remain open (or be re-attached) so that subsequent `node_start`, `node_end`, `pipeline_paused`, or `pipeline_end` events arriving from the engine SHALL be delivered to the page
- **AND** the run status in the header SHALL reflect the post-resume transition without requiring a manual page refresh

## ADDED Requirements

### Requirement: Project dashboard links to observability route

The project dashboard navigation SHALL include a link to `/projects/:id/observability` alongside the existing Agents / Pipelines / Runs tabs. The link SHALL be rendered as a top-level dashboard entry and SHALL use the same visual treatment as the other dashboard tabs.

The Observability route's sub-tabs (Sessions / Aggregates / Raw Timeline) SHALL be implemented using the existing `recharts` dependency for all charting, the existing `fetch`-based API client for data loading, and NO new UI component libraries beyond what `web/package.json` already declares.

#### Scenario: Dashboard shows observability link

- **GIVEN** the user is on `/projects/1`
- **WHEN** the page renders
- **THEN** a navigation entry labeled "Observability" SHALL be visible
- **AND** clicking it SHALL navigate to `/projects/1/observability`

#### Scenario: No new charting library is introduced

- **WHEN** the Observability route is shipped
- **THEN** `web/package.json` SHALL NOT gain any new charting or graph dependency beyond the pre-existing `recharts`, `@xyflow/react`, and `@dagrejs/dagre` entries
