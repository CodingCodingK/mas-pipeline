## MODIFIED Requirements

### Requirement: Run detail page streams events via SSE

`web/src/pages/RunDetailPage.tsx` SHALL render the pipeline DAG as its primary view via the `RunGraph` component, fetched from `GET /api/runs/:runId/graph` on mount. The page SHALL subscribe to `GET /api/runs/:runId/events` for live SSE updates and reattach the subscription whenever the run status transitions between `running` and `paused`. The page SHALL NOT render top-level Result, Timeline, Telemetry, or Event Log tabs; all per-node detail is reached by clicking a node in the DAG and reading the drawer that opens.

The page SHALL render the existing run header (status badge, pause/cancel/resume ops buttons) above the DAG. When the run status is `paused`, the page SHALL render `ResumePanel` as a banner above the DAG, NOT inside the node drawer.

When the page is entered with a `runId` of `pending` (newly triggered run not yet assigned an id) or before the graph fetch resolves, the page SHALL render `RunGraph` with an empty nodes array and a "Waiting for run to start…" placeholder inside the DAG area. It SHALL NOT render a separate pending-state view.

When the SSE stream closes with `pipeline_end`, `pipeline_failed`, or `terminal`, the page SHALL update the header status to the final value. The page SHALL also support loading a completed run by fetching `GET /api/runs/:runId` and `GET /api/runs/:runId/graph` on mount when no pending trigger is present.

#### Scenario: DAG renders on mount for a completed run

- **GIVEN** a completed run with three nodes
- **WHEN** the user navigates to `/runs/:runId`
- **THEN** the page SHALL fetch `GET /api/runs/:runId/graph`
- **AND** the page SHALL render three `RunGraph` nodes with their final statuses
- **AND** the page SHALL NOT render Result / Timeline / Telemetry / Event Log tabs

#### Scenario: SSE reattaches across pause↔running

- **GIVEN** a running pipeline transitions to `paused` then back to `running`
- **WHEN** the page observes the transition via SSE
- **THEN** the SSE subscription SHALL close and reopen with the new run state
- **AND** subsequent node events SHALL reach the DAG via the reopened stream

#### Scenario: Pending run unifies with DAG idle state

- **GIVEN** the user triggers a new pipeline run
- **WHEN** the page is entered with `runId="pending"`
- **THEN** the page SHALL render `RunGraph` with an empty nodes array
- **AND** display "Waiting for run to start…" inside the DAG area
- **AND** NOT render a separate pending-state spinner or skeleton

### Requirement: Vitest covers client and SSE parser

The repository SHALL include vitest tests under `web/src/__tests__/` that verify the API client header behavior, error mapping, and 204 handling, and verify the SSE parser against a canned `ReadableStream`. The suite SHALL additionally cover `RunNodeDrawer` segment rendering and empty states. `npm run test` inside `web/` SHALL run these tests via `vitest run` and exit with status 0 when they pass.

Component-level rendering tests (jsdom, React Testing Library) for pages remain out of scope; component-level tests for new leaf components (RunGraph, RunNodeDrawer) are in scope.

#### Scenario: Vitest suite passes including RunNodeDrawer

- **WHEN** `cd web && npm run test` runs in a fresh checkout after `npm install`
- **THEN** the test runner SHALL exit with status 0
- **AND** `client.test.ts`, `sse.test.ts`, `RunGraph.test.tsx`, and `RunNodeDrawer.test.tsx` SHALL all be reported as passing

## ADDED Requirements

### Requirement: Run node drawer exposes per-node output and telemetry

`web/src/components/RunNodeDrawer.tsx` SHALL be a right-side slide-out panel that opens when a node is clicked in `RunGraph` on `RunDetailPage`. The drawer SHALL accept props `{runId: string, nodeName: string | null, isOpen: boolean, onClose: () => void}` and SHALL fetch per-node data only when `isOpen` flips true.

When open, the drawer SHALL render four vertically-stacked segments in order:

1. **Output** — reads `outputs[nodeName]` from `GET /api/runs/:runId` response; renders as preformatted text truncated to 2000 characters with a "show more" affordance for longer outputs.
2. **Timeline** — reads `GET /api/telemetry/runs/:runId/timeline`, client-filters events whose `payload.node_name === nodeName`, and renders them as a table (ts / event_type / duration / stop_reason).
3. **Telemetry** — renders roll-up cards derived from the same timeline fetch (llm_call count, total tokens, total cost_usd, tool_call count).
4. **Events** — renders raw SSE events for this node as a scrollable log.

Each segment SHALL be a collapsible `<details open>` element so users can fold segments on narrow viewports.

The drawer footer SHALL contain a `<Link>` reading "See all events for this run in Observability →" that navigates to `/projects/:id/observability?sub=timeline&run=<runId>`. The drawer SHALL be closable via an X button, ESC key, and clicking the backdrop.

When `nodeName` is null or the drawer has not been opened, the drawer SHALL not fetch any data and SHALL render nothing.

#### Scenario: Drawer opens on node click and fetches data

- **GIVEN** `RunDetailPage` renders a DAG with three nodes for a completed run
- **WHEN** the user clicks the `researcher` node
- **THEN** `RunNodeDrawer` SHALL open with `nodeName="researcher"`
- **AND** it SHALL fire fetches for `GET /api/runs/:runId` and `GET /api/telemetry/runs/:runId/timeline`
- **AND** render four segments: Output, Timeline, Telemetry, Events

#### Scenario: Drawer filters timeline events by node

- **GIVEN** a run timeline containing 20 telemetry events across three nodes
- **WHEN** the drawer opens for the `writer` node
- **THEN** the Timeline segment SHALL render only events whose `payload.node_name` equals `writer`
- **AND** the Telemetry segment's roll-up counts SHALL reflect only those filtered events

#### Scenario: Deep link to Observability carries run filter

- **GIVEN** the drawer is open for a node of run `abc123` inside project `42`
- **WHEN** the user clicks the "See all events" link in the drawer footer
- **THEN** the browser SHALL navigate to `/projects/42/observability?sub=timeline&run=abc123`
- **AND** the Observability Raw Timeline sub-tab SHALL render events filtered to `run_id=abc123`

#### Scenario: Drawer closes via ESC, X button, or backdrop

- **GIVEN** the drawer is open
- **WHEN** the user presses ESC, clicks the X button, or clicks the backdrop
- **THEN** the drawer SHALL close and call `onClose`
- **AND** the DAG SHALL remain rendered unchanged

#### Scenario: Drawer renders nothing when no node selected

- **GIVEN** `RunDetailPage` is mounted but no node has been clicked
- **WHEN** the initial render completes
- **THEN** `RunNodeDrawer` SHALL not fetch any data
- **AND** SHALL not render any DOM under the drawer root

### Requirement: Observability raw timeline accepts run_id filter

`web/src/pages/ObservabilityPage.tsx`'s Raw Timeline sub-tab SHALL read a `run` query parameter from the URL and pass it through to `GET /api/telemetry/turns` as a `run_id=<value>` filter. The backend query function `list_project_turns` in `src/telemetry/query.py` SHALL accept an optional `run_id` argument and, when supplied, append a `run_id = :run_id` clause to its WHERE filter.

When the `run` parameter is present, the Raw Timeline SHALL display a removable filter chip indicating the active run filter.

#### Scenario: Raw timeline filters by run_id from URL

- **GIVEN** a project with three runs, two agent_turn rows per run
- **WHEN** the user navigates to `/projects/:id/observability?sub=timeline&run=abc123`
- **THEN** the Raw Timeline SHALL render exactly two rows
- **AND** both rows SHALL belong to run `abc123`
- **AND** a removable chip labeled "run: abc123" SHALL appear above the table

#### Scenario: Removing the run filter resets the view

- **GIVEN** the Raw Timeline is filtered by `run=abc123`
- **WHEN** the user clicks the chip's close icon
- **THEN** the URL SHALL drop the `run` query parameter
- **AND** the Raw Timeline SHALL re-fetch without the `run_id` filter
- **AND** all six rows across all three runs SHALL render
