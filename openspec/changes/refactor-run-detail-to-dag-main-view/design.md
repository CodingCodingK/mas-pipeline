## Context

`improve-run-observability-and-ops` landed RunGraph, `/runs/{id}/graph`, `/runs/{id}/events`, and the pause/cancel/resume ops buttons, but the RunDetailPage main view was left on the old four-tab layout (Result / Timeline / Telemetry / Event Log) because the tab→DAG rewrite was a larger structural change than fit that change's scope (documented in tasks.md 8.1/8.2/8.4 as "deferred to follow-up"). All backend feeds are ready. All that is missing is the frontend surface.

Current `RunDetailPage.tsx` is ~600 lines: it owns four independent `useAsync` hooks (one per tab), a primary SSE subscription, a resubscribe SSE effect for pause↔running transitions, a conditional `ResumePanel`, an `RunOpsButtons` header, and the tab-switcher logic that shows/hides each pane. The DAG and ResumePanel were bolted on above the old tabs; the result is visually crowded and doesn't match the mental model users actually have (pipelines are graphs, not tab trees).

## Goals / Non-Goals

**Goals:**
- Make DAG the primary RunDetail view; any node detail is one click away.
- Collapse four top-level tabs into one drawer that opens on demand.
- Keep the existing run header (status + ops buttons + ResumePanel) untouched.
- Zero backend changes.
- Per-node data fetched lazily (only when the drawer opens).
- Preserve the SSE resubscribe behavior that fixed the "silent click" bug.

**Non-Goals:**
- No change to `RunGraph.tsx` internals (layout, colors, edge styles).
- No change to backend endpoints, telemetry shapes, or pricing config.
- No `AgentRunDetailDrawer` merger — that drawer is for agent runs (chat / pipeline agent detail), `RunNodeDrawer` is for pipeline-node detail. They can share a visual shell later if desired, but this change does not consolidate them.
- No per-node SSE filtering. The main page still subscribes once; the drawer re-reads from the same cached event list when opened.
- No offline / caching layer. Drawer fetches on open each time; re-opens refetch.

## Decisions

### Decision 1: Drawer holds four segments, not four tabs

**Choice**: `RunNodeDrawer` renders **Output**, **Timeline**, **Telemetry**, **Events** as vertically-stacked collapsible sections (all open by default for wide screens; each collapsible for narrow). Not as sub-tabs.

**Why not sub-tabs**: sub-tabs add a click to reach every piece of data and hide information by default. The four sections are small enough (Output ~preview, Timeline ~20 rows, Telemetry ~5 cards, Events ~10 rows per-node) to coexist in one scrollable panel. This mirrors how `AgentRunDetailDrawer` lays out its transcript + tool calls + metadata without sub-tabs.

**Trade-off**: the drawer gets long. Acceptable because scrolling is cheaper than clicking.

### Decision 2: Drawer data-fetching is per-open, per-node

**Choice**: `RunNodeDrawer` takes `{runId, nodeName, isOpen}`. When `isOpen` flips true, it fires three fetches in parallel:
- `GET /api/runs/:runId` (for `outputs[nodeName]`)
- `GET /api/telemetry/runs/:runId/timeline` (filtered client-side to events with `payload.node_name == nodeName`)
- `GET /api/runs/:runId/graph` (for node status + role — already rendered by the parent, but the drawer re-reads so it can stay decoupled)

Closing and re-opening the drawer re-fires. No cache.

**Why not lift state to `RunDetailPage`**: the main page already has the full timeline from SSE; lifting would couple drawer state to the SSE buffer and make pause/resume edge cases harder to reason about. Fresh fetches on open are simple and the RTT is under 200ms for all three endpoints.

### Decision 3: Event Log cross-run view is removed, not relocated

**Choice**: Delete the "Event Log" tab entirely. Drawer footer contains one `<Link>` — "See all events for this run in Observability →" — that navigates to `/projects/:id/observability?sub=timeline&run=<runId>`.

**Why**: the cross-run event log on `RunDetailPage` was always a duplicate of the Raw Timeline sub-tab in Observability. Having two surfaces for the same data forces users to pick; having one makes the boundary clean (RunDetail = this run visually; Observability = cross-run / flat tables).

**Risk**: users who bookmarked a URL hash pointing to the old event log tab will see the DAG instead. Acceptable — no stable hash URL was documented.

**Follow-up requirement**: the existing Observability Raw Timeline sub-tab already accepts filters via `useMemo` query string. It needs to additionally accept `run=<id>` so the deep-link actually filters. This is a small addition to `RawTimelineTab` in `ObservabilityPage.tsx` and to `list_project_turns` in `query.py`. Treat this as part of the spec delta, not a separate change.

### Decision 4: `pending` run state unifies with DAG idle state

**Choice**: When `runId === "pending"` or the initial `GET /runs/:runId/graph` has not yet returned, `RunDetailPage` renders `RunGraph` with an empty nodes array and a "Waiting for run to start…" placeholder inside the RunGraph area. No separate pending-only view.

**Why not keep the old pending SSE spinner**: the pending path was only ~40 lines but doubled the cognitive load of `RunDetailPage`. Unifying it means one render path, one state machine, one set of tests.

### Decision 5: ResumePanel stays above DAG, not inside drawer

**Choice**: `ResumePanel` (approve / reject / edit) renders as a banner above the RunGraph when the run is paused. Clicking it does NOT require opening the drawer.

**Why**: pausing fires at a specific node, but the approval action conceptually belongs to the run, not the node (the interrupt payload is `{node, output}` but the user's decision — approve/reject/edit — applies to the whole run's next step). Putting it in the drawer would gate approval behind a node click. The banner stays prominent, matches the pattern used by the existing 8.6 `ResumePanel` rewrite.

## Risks / Trade-offs

- **Regression risk — SSE resubscribe**: the 8.3 fix (second `useEffect` on `[liveStream, runId, status]` reattaching on pause↔running) lives inside `RunDetailPage`. The rewrite MUST preserve this effect verbatim. → Mitigation: copy the effect and its deps before deleting tab logic; add a vitest that mocks an SSE transition and asserts reconnect count.
- **Drawer / DAG state sync**: if the user clicks node A, then the pipeline progresses and A's status changes, the open drawer's status badge goes stale. → Mitigation: drawer subscribes (via a prop) to the same `nodes` array from `RunGraph`; when the parent re-renders from a new SSE event, the drawer re-derives the current node's status without refetching.
- **`@xyflow/react` jsdom hostility**: `ResizeObserver` must be polyfilled in vitest setup. Already done for `RunGraph.test.tsx`; extend to `RunNodeDrawer.test.tsx`.
- **Long drawer on narrow viewports**: all four sections stacked can exceed viewport height. → Mitigation: drawer is independently scrollable; sections are `<details open>` so users can collapse Output/Timeline on mobile.
- **Deep link `run=<id>` filter gap**: Observability RawTimelineTab currently filters on role/status but not run. If the spec delta ships without this filter addition, the deep link will render cross-run data ignoring the `run` param. → Mitigation: include the filter addition in the same change (see Decision 3).

## Migration Plan

1. Ship `RunNodeDrawer.tsx` + tests first. It's a leaf component; merging it in isolation is safe (nothing imports it yet).
2. Rewrite `RunDetailPage.tsx`. Keep git history clean via one commit that deletes the old tab code and adds the DAG + drawer mount.
3. Extend `ObservabilityPage.tsx` `RawTimelineTab` to read `run` query param and pass it through the API call. Extend `list_project_turns` in `query.py` to accept `run_id` filter.
4. Update `web-frontend/spec.md` with the modified requirement + new requirement.
5. Regression: `npx tsc -b` / `npm run test` / `npm run build` / manual blog_with_review interrupt path.

Rollback: revert the `RunDetailPage.tsx` commit. `RunNodeDrawer.tsx` is a leaf and can stay unused.

## Open Questions

None. All design decisions above are ready for implementation without further discussion.
