## ADDED Requirements

### Requirement: Project observability route with three sub-tabs

The web UI SHALL expose a new route `/projects/:id/observability` that renders a tabbed layout with three sub-tabs: **Sessions**, **Aggregates**, and **Raw Timeline**. The active sub-tab SHALL be stored in the URL as a `?sub=` query parameter with values `sessions`, `aggregates`, or `timeline` (default `aggregates`).

The Observability route SHALL be linked from the existing project dashboard navigation (alongside Agents / Pipelines / Runs tabs). Navigating to the route SHALL require the project to exist; for an unknown project id the page SHALL render a 404 state.

#### Scenario: Observability route renders default sub-tab

- **GIVEN** the user navigates to `/projects/1/observability` without a query parameter
- **WHEN** the page mounts
- **THEN** the Aggregates sub-tab SHALL be active

#### Scenario: Sub-tab state persists in URL

- **GIVEN** the user is on `/projects/1/observability?sub=sessions`
- **WHEN** the page renders
- **THEN** the Sessions sub-tab SHALL be active

#### Scenario: Unknown project renders 404

- **GIVEN** the user navigates to `/projects/99999/observability` for a non-existent project
- **WHEN** the page mounts and fetches project data
- **THEN** a 404 state SHALL be rendered

### Requirement: Sessions sub-tab lists chat sessions and shows per-session turn timeline

The Sessions sub-tab SHALL fetch and display all `chat_sessions` belonging to the current project via `GET /api/telemetry/sessions?project_id=<id>`. Each session row SHALL show session key, channel, mode, created_at, and last_active_at. Clicking a row SHALL open a detail view showing a horizontal timeline of the session's `agent_turn` events, with one row per turn and columns for start time, duration, tokens, tool call count, and status.

The session list SHALL support pagination with a default page size of 50. The session detail timeline SHALL load up to 500 turns per session; sessions exceeding this SHALL show a "showing latest 500 turns" banner.

#### Scenario: Session list renders on tab open

- **GIVEN** project 1 has three chat sessions
- **WHEN** the user opens the Sessions sub-tab
- **THEN** three session rows SHALL be rendered
- **AND** each row SHALL display the session's channel and mode

#### Scenario: Click session opens turn timeline

- **GIVEN** a session with 20 recorded agent turns
- **WHEN** the user clicks the session row
- **THEN** a detail view SHALL render 20 turn entries in order
- **AND** each entry SHALL show its tokens, duration, and tool-call count

### Requirement: Aggregates sub-tab renders charts using recharts

The Aggregates sub-tab SHALL render four recharts-based charts:

1. **Cost over time** — line chart of `cost_usd` summed per time bucket
2. **Token usage over time** — stacked area chart of input/output/cache tokens
3. **Turn count by status** — bar chart grouped by time bucket, split by status
4. **Error rate** — line chart of the ratio of `error` events to `agent_turn` events per bucket

The sub-tab SHALL offer three window selectors: 24h (hourly buckets), 7d (daily buckets), and 30d (daily buckets). Switching the window SHALL re-fetch `GET /api/telemetry/aggregate?project_id=<id>&window=24h|7d|30d`. The charts SHALL use the existing `recharts` dependency already in `web/package.json` — no new charting library SHALL be introduced.

When any chart has zero data points for the selected window, the chart SHALL render an empty-state placeholder ("No data for this window") instead of an empty canvas.

#### Scenario: Window toggle re-fetches data

- **GIVEN** the Aggregates sub-tab is showing the 24h window
- **WHEN** the user clicks the "7d" button
- **THEN** a new fetch SHALL be issued to `/api/telemetry/aggregate?project_id=<id>&window=7d`
- **AND** all four charts SHALL re-render with the new data

#### Scenario: Empty window shows placeholder

- **GIVEN** the project has no telemetry events in the last 24 hours
- **WHEN** the user selects the 24h window
- **THEN** each chart area SHALL render a "No data for this window" placeholder instead of an empty canvas

#### Scenario: Cost chart reflects non-zero values when pricing is wired correctly

- **GIVEN** the project has at least one `llm_call` event in the window with a non-null `cost_usd` value
- **WHEN** the Aggregates sub-tab renders
- **THEN** the cost-over-time chart SHALL show a non-zero data point
- **AND** the chart's y-axis SHALL be labeled in USD

### Requirement: Raw Timeline sub-tab streams recent agent_turn events

The Raw Timeline sub-tab SHALL render a scrollable list of recent `agent_turn` events across all sessions in the project. It SHALL fetch via `GET /api/telemetry/turns?project_id=<id>&limit=100` and support two filter controls:

- **Role filter**: dropdown listing distinct `agent_role` values seen in the current response, plus "All"
- **Status filter**: dropdown with values `all`, `done`, `interrupt`, `error`, `idle_exit`

Selecting a filter SHALL re-fetch with the appropriate query parameters appended. Each row SHALL show timestamp, agent role, duration, tokens, input preview, output preview, and status badge.

#### Scenario: Role filter narrows the list

- **GIVEN** the Raw Timeline shows 100 mixed-role turns
- **WHEN** the user selects the `researcher` role filter
- **THEN** a new fetch SHALL be issued with `role=researcher`
- **AND** the list SHALL render only rows where `agent_role="researcher"`

#### Scenario: Status filter narrows by stop_reason

- **GIVEN** the Raw Timeline is showing all statuses
- **WHEN** the user selects the `error` status filter
- **THEN** a new fetch SHALL be issued with `status=error`
- **AND** only rows with `stop_reason="error"` SHALL be rendered

### Requirement: Observability endpoints accept project_id filter

The existing telemetry endpoints `/api/telemetry/sessions`, `/api/telemetry/aggregate`, and `/api/telemetry/turns` SHALL accept a `project_id` query parameter that filters results to the specified project. Where the endpoints previously returned cross-project data by default, they SHALL continue to do so when `project_id` is omitted, preserving backward compatibility.

When `project_id` is provided and corresponds to a non-existent project, the endpoints SHALL return HTTP 404. When `project_id` is provided and valid, the response SHALL include only events/rows where the telemetry event's `project_id` field matches.

#### Scenario: Project filter isolates one project's data

- **GIVEN** two projects A (id=1) and B (id=2), each with telemetry events
- **WHEN** a client issues `GET /api/telemetry/turns?project_id=1`
- **THEN** the response SHALL contain only turns whose telemetry event has `project_id=1`
- **AND** no turn from project B SHALL appear

#### Scenario: Missing project_id returns 404

- **WHEN** a client issues `GET /api/telemetry/aggregate?project_id=99999&window=7d` for a non-existent project
- **THEN** the response SHALL be HTTP 404

#### Scenario: Omitted project_id preserves backward behavior

- **WHEN** a client issues `GET /api/telemetry/turns` with no `project_id` parameter
- **THEN** the response SHALL return turns from all projects the API key has access to, matching the pre-change behavior
