# web-frontend Specification

## Purpose
TBD - created by archiving change add-web-frontend-mvp. Update Purpose after archive.
## Requirements
### Requirement: Vite + React + TypeScript SPA scaffolding

The repository SHALL include a `web/` directory containing a standalone Vite project configured for React 18, TypeScript 5, and Tailwind CSS 3. The project SHALL produce a static bundle via `npm run build` into `web/dist/` and be served independently of the FastAPI backend during development.

The project SHALL provide the following npm scripts:

- `dev` — start Vite dev server (default port 5173)
- `build` — `vite build`
- `typecheck` — `tsc --noEmit`
- `test` — `vitest run`

The project's TypeScript configuration SHALL enable `strict: true` and configure a path alias `@/*` resolving to `src/*`.

#### Scenario: Build succeeds from a clean checkout

- **GIVEN** a fresh clone with `node_modules` absent
- **WHEN** a developer runs `cd web && npm install && npm run build`
- **THEN** the command SHALL exit with status 0
- **AND** `web/dist/index.html` SHALL exist after the build

#### Scenario: Typecheck rejects type errors

- **GIVEN** any `.ts` / `.tsx` file with a type mismatch
- **WHEN** `npm run typecheck` runs
- **THEN** the command SHALL exit with non-zero status and print the error location

### Requirement: API client injects X-API-Key header

`web/src/api/client.ts` SHALL export a `request<T>(method, path, body?): Promise<T>` function and `get` / `put` / `post` / `del` convenience wrappers. The client SHALL read `import.meta.env.VITE_API_BASE` and `import.meta.env.VITE_API_KEY` at call time. When `VITE_API_KEY` is a non-empty string, the client SHALL attach it as an `X-API-Key` header on every request.

The client SHALL throw an `ApiError` subclass of `Error` carrying `{status: number, body: unknown}` when the response status is not in the 2xx range. A 204 response SHALL resolve to `undefined` without attempting to parse the body.

#### Scenario: Header is added when key is configured

- **GIVEN** `VITE_API_KEY` is the string `"secret"`
- **WHEN** `client.get("/agents")` is invoked
- **THEN** the underlying `fetch` call SHALL include the header `X-API-Key: secret`

#### Scenario: Header is omitted when key is empty

- **GIVEN** `VITE_API_KEY` is an empty string (development mode)
- **WHEN** `client.get("/agents")` is invoked
- **THEN** the underlying `fetch` call SHALL NOT include an `X-API-Key` header

#### Scenario: Non-2xx response raises ApiError

- **GIVEN** a mocked `fetch` returning status 404 with body `{"detail":"agent not found"}`
- **WHEN** `client.get("/agents/nobody")` is awaited
- **THEN** the promise SHALL reject with an `ApiError` instance
- **AND** `error.status` SHALL equal `404`
- **AND** `error.body.detail` SHALL equal `"agent not found"`

#### Scenario: 204 response resolves undefined

- **GIVEN** a mocked `fetch` returning status 204 with an empty body
- **WHEN** `client.del("/agents/writer")` is awaited
- **THEN** the promise SHALL resolve to `undefined`

### Requirement: SSE consumer via fetch + ReadableStream

`web/src/api/sse.ts` SHALL export `fetchEventStream(path, {signal?, body?, onEvent})` that posts to the given path with the API key header attached, reads the response body as a UTF-8 byte stream, and parses Server-Sent Event frames. For every complete frame, it SHALL invoke `onEvent({type: string, data: string})`. The function SHALL return a promise that resolves when the stream closes normally and rejects when it errors or the `AbortSignal` fires.

The parser SHALL:
- Accept lines of the form `event: <type>` setting the frame type
- Accept lines of the form `data: <payload>` as the frame data
- Ignore lines starting with `:` (heartbeat comments)
- Treat a blank line as the frame delimiter, after which `onEvent` SHALL be called
- Reset the pending type to `"message"` after each emitted frame

#### Scenario: Parses event and data lines into frames

- **GIVEN** a `ReadableStream` yielding the bytes of `"event: pipeline_start\ndata: {\"run_id\":\"x\"}\n\nevent: pipeline_end\ndata: {}\n\n"`
- **WHEN** `fetchEventStream(...)` runs with a mocked fetch returning this stream
- **THEN** `onEvent` SHALL be called exactly twice
- **AND** the first call SHALL receive `{type: "pipeline_start", data: "{\"run_id\":\"x\"}"}`
- **AND** the second call SHALL receive `{type: "pipeline_end", data: "{}"}`

#### Scenario: Heartbeat lines are ignored

- **GIVEN** a stream containing `": ping\n\n"` between two real events
- **WHEN** `fetchEventStream` parses the stream
- **THEN** no `onEvent` call SHALL be emitted for the heartbeat
- **AND** the two real events SHALL still be emitted correctly

### Requirement: Projects list page

`web/src/pages/ProjectsPage.tsx` SHALL render a list view of all projects fetched from `GET /api/projects`. Each project SHALL be displayed as a card showing its `id`, `name`, `pipeline`, and `status`. Clicking a card SHALL navigate to `/projects/:id`.

The page SHALL render a loading placeholder while the fetch is in flight, an inline error message on failure, and an empty-state message when the response has zero items.

#### Scenario: Lists projects on mount

- **GIVEN** the backend returns two projects
- **WHEN** the page mounts
- **THEN** two cards SHALL be rendered in the document

#### Scenario: Shows error on fetch failure

- **GIVEN** the backend returns 401
- **WHEN** the page mounts
- **THEN** an error block SHALL be shown containing the status and detail

### Requirement: Project detail page with agent/pipeline/run tabs

`web/src/pages/ProjectDetailPage.tsx` SHALL render a tab container for a single project. The active tab SHALL be stored in the URL as a `?tab=` query parameter with one of the values `agents`, `pipelines`, or `runs` (default `agents`). Each tab SHALL render its own component fetching the appropriate REST endpoints:

- `AgentsTab` → `GET /api/projects/:id/agents` (merged view)
- `PipelinesTab` → `GET /api/projects/:id/pipelines` (merged view)
- `RunsTab` → `GET /api/projects/:id/runs` (run list, if endpoint exists) plus a "Trigger" form

The merged-view tabs SHALL display each item's `source` field as a colored pill (`global` / `project-only` / `project-override`). Clicking a row SHALL open an inline file editor.

#### Scenario: Tab state persists in URL

- **GIVEN** the user is on `/projects/1?tab=pipelines`
- **WHEN** the page renders
- **THEN** the pipelines tab SHALL be active

#### Scenario: Source pill reflects merged-view value

- **GIVEN** the merged view returns `[{name: "writer", source: "project-override"}]`
- **WHEN** `AgentsTab` renders
- **THEN** the row for `writer` SHALL display a pill labeled `project-override`
- **AND** the pill SHALL use the amber Tailwind color class

### Requirement: File editor component writes to project layer

`web/src/components/FileEditor.tsx` SHALL render a `<textarea>` containing the current agent or pipeline content, a "Save" button, and a "Delete" button. Saving SHALL issue `PUT /api/projects/:id/{agents|pipelines}/:name` with `{content}`. Deleting SHALL issue `DELETE /api/projects/:id/{agents|pipelines}/:name`.

Invalid names (422) and in-use agents (409 with `references` array) SHALL render their errors inline. The editor SHALL NOT provide syntax highlighting — plain text with monospace font is sufficient for the MVP.

#### Scenario: Save issues PUT with content

- **GIVEN** the editor is open for `writer` in project 42
- **WHEN** the user edits the textarea and clicks Save
- **THEN** the client SHALL send `PUT /api/projects/42/agents/writer` with the edited content in the body

#### Scenario: 409 on delete renders references inline

- **GIVEN** the backend returns 409 with `{detail: "...", references: [{project_id: null, pipeline: "blog", role: "writer"}]}`
- **WHEN** the user clicks Delete
- **THEN** an inline error SHALL render listing the blocking pipeline references

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

