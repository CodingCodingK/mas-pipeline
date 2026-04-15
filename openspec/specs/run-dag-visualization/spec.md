# run-dag-visualization Specification

## Purpose
TBD - created by archiving change improve-run-observability-and-ops. Update Purpose after archive.
## Requirements
### Requirement: Run graph read endpoint

The system SHALL expose `GET /api/runs/{run_id}/graph` returning a JSON payload describing the pipeline DAG for a single run. The payload SHALL be a pure read — it SHALL NOT write to any DB table and SHALL NOT mutate in-memory state.

The response body SHALL have the shape:

```json
{
  "run_id": "string",
  "pipeline": "string",
  "status": "running|paused|completed|failed|cancelled",
  "nodes": [
    {
      "id": "string",
      "name": "string",
      "role": "string",
      "status": "idle|running|completed|failed|paused|cancelled|skipped",
      "started_at": "ISO8601 | null",
      "finished_at": "ISO8601 | null",
      "output_preview": "string | null"
    }
  ],
  "edges": [
    { "from": "string", "to": "string", "kind": "sequence|conditional" }
  ]
}
```

Nodes SHALL be derived by joining the pipeline YAML definition (topology) with the `agent_runs` rows for this run (live state). Edges SHALL be derived from the YAML's declared node sequence. `output_preview` SHALL be the first 200 characters of the node's `output` field, HTML-escaped, or `null` if the node has not produced output yet.

Node `status` values SHALL be a closed set: `idle`, `running`, `completed`, `failed`, `paused`, `cancelled`, `skipped`. Any node whose YAML definition exists but which has no matching `agent_runs` row SHALL be reported with `status="idle"`.

#### Scenario: Graph endpoint returns nodes and edges for a running pipeline

- **GIVEN** a pipeline `blog_with_review` with nodes `planner → writer → editor` is running, with `planner` completed and `writer` currently executing
- **WHEN** a client issues `GET /api/runs/{run_id}/graph`
- **THEN** the response SHALL be HTTP 200 with three entries in `nodes` and two entries in `edges`
- **AND** `nodes[0].status` SHALL be `"completed"`, `nodes[1].status` SHALL be `"running"`, and `nodes[2].status` SHALL be `"idle"`

#### Scenario: Graph endpoint reports paused node status

- **GIVEN** a pipeline is paused at the `editor_interrupt` node
- **WHEN** a client issues `GET /api/runs/{run_id}/graph`
- **THEN** the node entry for `editor` SHALL have `status="paused"` and a non-null `output_preview`

#### Scenario: Output preview is truncated to 200 characters

- **GIVEN** a completed node whose `output` field is a 5000-character markdown string
- **WHEN** a client issues `GET /api/runs/{run_id}/graph`
- **THEN** the node's `output_preview` SHALL be exactly 200 characters long

#### Scenario: 404 on unknown run_id

- **WHEN** a client issues `GET /api/runs/nonexistent_id/graph`
- **THEN** the response SHALL be HTTP 404

### Requirement: DAG client renderer using React Flow

The web UI SHALL render the run graph using `@xyflow/react` (already declared in `web/package.json`) with layout computed by `@dagrejs/dagre`. A new component `web/src/components/RunGraph.tsx` SHALL accept `{nodes, edges}` props in the shape returned by `GET /api/runs/{run_id}/graph` and SHALL render each node with a background color derived from its `status` field.

The color mapping SHALL be:
- `idle` → neutral gray
- `running` → blue with animated pulse
- `completed` → green
- `failed` → red
- `paused` → amber
- `cancelled` → dark gray
- `skipped` → light gray with dashed border

Clicking a node SHALL invoke an `onNodeClick(nodeId)` callback passed as a prop. The component SHALL NOT call the backend itself — data fetching is the parent's responsibility.

#### Scenario: Node color reflects status

- **GIVEN** a `RunGraph` rendered with one completed and one running node
- **WHEN** the component mounts
- **THEN** the completed node SHALL have a green background class
- **AND** the running node SHALL have a blue background class with the pulse animation

#### Scenario: Click invokes callback

- **GIVEN** a `RunGraph` with `onNodeClick` prop set to a spy
- **WHEN** the user clicks the `editor` node
- **THEN** the spy SHALL be called exactly once with the argument `"editor"`

### Requirement: Node drawer reveals full turn log on click

The run detail page SHALL open a collapsible side drawer when a node is clicked in the DAG. The drawer SHALL display the full event/turn log for that node — the same data that the legacy linear log view currently shows — fetched via the existing `GET /api/runs/{run_id}/events` or equivalent endpoint. The drawer SHALL be closable without leaving the page.

The legacy scrolling event log SHALL NOT appear on the main run detail surface. It SHALL only be accessible through the node drawer.

#### Scenario: Drawer opens with node context

- **GIVEN** the run detail page is showing the DAG for a run with an `editor` node
- **WHEN** the user clicks the `editor` node
- **THEN** a drawer SHALL slide in containing only events/turns where the active agent role or node matches `editor`

#### Scenario: Drawer does not block SSE updates

- **GIVEN** the drawer is open for one node while another node transitions from running to completed
- **WHEN** the SSE stream delivers the new state
- **THEN** the underlying DAG SHALL update the other node's color in place
- **AND** the drawer contents SHALL remain focused on the originally selected node

