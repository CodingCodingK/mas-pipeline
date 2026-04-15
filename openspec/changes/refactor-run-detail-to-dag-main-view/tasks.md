## 1. RunNodeDrawer component (leaf-first)

- [x] 1.1 Create `web/src/components/RunNodeDrawer.tsx` with props `{runId, nodeName, isOpen, onClose}` and render nothing when `!isOpen || !nodeName`
- [x] 1.2 Implement the 3-parallel-fetch on `isOpen=true`: `GET /api/runs/:runId`, `GET /api/telemetry/runs/:runId/timeline`, `GET /api/runs/:runId/graph`
- [x] 1.3 Render four `<details open>` segments in order: Output / Timeline / Telemetry / Events
- [x] 1.4 Output segment: read `outputs[nodeName]`, preformatted, truncate at 2000 chars with "show more" toggle
- [x] 1.5 Timeline segment: client-filter timeline events by `payload.node_name === nodeName`, render ts / event_type / duration / stop_reason table
- [x] 1.6 Telemetry segment: roll-up cards (llm_call count, total input_tokens + output_tokens, total cost_usd, tool_call count) derived from the same filtered timeline
- [x] 1.7 Events segment: scrollable log of raw SSE events for this node
- [x] 1.8 Drawer footer: `<Link to="/projects/:projectId/observability?sub=timeline&run=<runId>">See all events for this run in Observability →</Link>`
- [x] 1.9 Close affordances: X button (top-right), ESC key listener, backdrop click-through
- [x] 1.10 Polyfill `ResizeObserver` in the vitest setup (already done for RunGraph; extend if missing)
- [x] 1.11 Add `web/src/__tests__/RunNodeDrawer.test.tsx` covering: renders nothing when closed, four segments present when open, timeline filter matches node_name, empty state when `outputs[nodeName]` is missing, deep-link URL format
- [x] 1.12 `cd web && npx tsc -b && npm run test` → green before moving on

## 2. Observability run_id filter

- [x] 2.1 Extend `list_project_turns` in `src/telemetry/query.py` to accept optional `run_id: str | None = None` and append `run_id = :run_id` to WHERE when supplied
- [x] 2.2 Extend `GET /api/telemetry/turns` in `src/telemetry/api.py` to accept `run_id` query parameter and forward it
- [x] 2.3 Update `ObservabilityPage.tsx` `RawTimelineTab` to read `run` from URL, pass it as `run_id` to the API call, and render a removable filter chip when active
- [x] 2.4 Clicking the chip's close icon drops `run` from the URL and re-fetches

## 3. RunDetailPage rewrite

- [x] 3.1 Copy the current SSE resubscribe effect (the `useEffect` on `[liveStream, runId, status]`) verbatim to a temporary scratch file — this MUST be preserved
- [x] 3.2 Delete the four top-level tab switchers and their per-tab `useAsync` hooks in `RunDetailPage.tsx`
- [x] 3.3 Replace the tab pane area with `<RunGraph nodes={graph.nodes} edges={graph.edges} onNodeClick={setSelectedNode} />`
- [x] 3.4 Add `selectedNode` state + `<RunNodeDrawer runId={runId} nodeName={selectedNode} isOpen={!!selectedNode} onClose={() => setSelectedNode(null)} />`
- [x] 3.5 Paste the SSE resubscribe effect back in and verify `[liveStream, runId, status]` deps are unchanged
- [x] 3.6 Keep the run header (status badge, `RunOpsButtons`) unchanged above the DAG
- [x] 3.7 Keep `ResumePanel` as a banner rendered above the DAG when `status === "paused"`, NOT inside the drawer
- [x] 3.8 Unify `pending` state: render `RunGraph` with empty nodes + "Waiting for run to start…" placeholder; no separate pending branch
- [x] 3.9 Remove any dead imports (`useTabs`, old per-tab components, `EventLog` cross-run helpers)

## 4. Spec delta and validation

- [x] 4.1 `openspec validate refactor-run-detail-to-dag-main-view --strict` → must pass
- [x] 4.2 `cd web && npx tsc -b` → exit 0
- [x] 4.3 `cd web && npm run test` → all passing (including new `RunNodeDrawer.test.tsx`)
- [x] 4.4 `cd web && npm run build` → dist regenerates, no errors
- [x] 4.5 Manual smoke: trigger `blog_with_review` to interrupt, click the paused reviewer node in the DAG, confirm the drawer opens with Output + Timeline + Telemetry + Events segments populated — **deferred to `.plan/wrap_up_checklist.md` §9 人工测试 "RunDetail DAG drawer 冒烟"**
- [x] 4.6 Manual smoke: click "See all events" deep link from drawer footer, confirm Observability Raw Timeline renders with the run filter chip active — **deferred to §9 "Observability deep-link 冒烟"**
- [x] 4.7 Manual smoke: trigger a run, approve from the ResumePanel banner above the DAG, confirm the pipeline advances and the DAG re-renders with updated node statuses — **deferred to §9 "Resume ↔ DAG 再渲染冒烟"**

## 5. Archive prep

- [x] 5.1 Update `.plan/wrap_up_checklist.md` §8: mark 8.1, 8.2, 8.4 as shipped via this change (previously deferred)
- [x] 5.2 Commit with message referencing this change id
