## Why

`RunDetailPage` currently stacks four top-level tabs (Result / Timeline / Telemetry / Event Log) above a thin status header. The RunGraph component and `GET /runs/{id}/graph` endpoint landed in the previous change (`improve-run-observability-and-ops`) but were never wired into the main view — §8 tasks 8.1/8.2/8.4 were explicitly deferred to this change. Users still cannot see which node in a pipeline is running, paused, or failed without cross-referencing Event Log rows. The DAG visualization exists, the backend feeds it, and the drawer pattern is already used by `AgentRunDetailDrawer` — it just needs to become the primary RunDetail surface.

## What Changes

- **BREAKING** `RunDetailPage.tsx` drops the four-tab layout. DAG (`RunGraph`) takes the main area; the run header (status / ops buttons / ResumePanel) stays on top.
- Clicking a node in the DAG opens a new `RunNodeDrawer` component (right-side slide-out) containing four segments for that node: **Output**, **Timeline**, **Telemetry**, **Events** — replacing the removed top-level tabs.
- Per-node output / timeline / telemetry fetching moves into the drawer. `RunDetailPage` stops fetching them at mount.
- Cross-run Event Log (all events, unfiltered) is removed from `RunDetailPage`. A link at the drawer footer deep-links to `/projects/:id/observability?sub=timeline&run=<id>` which already renders the same data via the existing Raw Timeline sub-tab.
- `pending` run state no longer takes a separate code path: the DAG renders with every node in `idle` status until the first SSE event arrives.
- Vitest coverage: new `RunNodeDrawer.test.tsx` for segment rendering + empty state; the existing `RunDetailPage` SSE test is relocated/rewritten to cover the DAG-primary flow.

## Capabilities

### New Capabilities

None. This is a UI refactor of an existing capability.

### Modified Capabilities

- `web-frontend`: the "Run detail page streams events via SSE" requirement is rewritten. It no longer describes a tabbed event log — it describes a DAG-primary view with a node drawer. A new requirement "Run node drawer exposes per-node output and telemetry" is added. The "Vitest covers client and SSE parser" requirement is amended to additionally cover `RunNodeDrawer` rendering.

## Impact

- **Frontend code**: `web/src/pages/RunDetailPage.tsx` (~600 lines → ~250 lines); new `web/src/components/RunNodeDrawer.tsx`; new `web/src/__tests__/RunNodeDrawer.test.tsx`.
- **Backend**: zero changes. All endpoints (`/runs/{id}/graph`, `/runs/{id}/events`, `/runs/{id}/pause|cancel|resume`, `/telemetry/runs/{id}/timeline`) already exist from the previous change.
- **Spec**: `openspec/specs/web-frontend/spec.md` gets one requirement rewrite + one new requirement + one amendment.
- **No dependency changes**. `RunGraph` uses `@xyflow/react` + `@dagrejs/dagre`, already in `web/package.json`.
- **Migration**: users lose the standalone cross-run Event Log on `RunDetailPage`; they gain deep-linking to Observability Raw Timeline with the same data. No backend data migration.
