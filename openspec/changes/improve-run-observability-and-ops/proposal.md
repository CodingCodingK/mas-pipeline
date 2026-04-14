## Why

**Pipeline runs are a black box from the UI.** Users who open a run detail page today see a flat list of agent_turn rows — they cannot tell which pipeline node is currently executing, which edge the graph is about to traverse, or where a failure actually happened. The detail page is 1461 LOC of `RunDetailPage.tsx` that renders everything as a scrolling log; there is no operator affordance for **pause** or **cancel**, and the `paused → approve|reject|edit` interaction has a known front-end bug where clicking the buttons appears silent even though the backend has already resumed the run. On top of that, the Dashboard has no project-level observability surface — telemetry events exist in PG and are exposed by `/api/telemetry/*`, but nothing in the web UI reads them, so the `cost_usd` column shows 0 across every run even though `src/telemetry/pricing.py` has a working 11-model pricing table.

All four gaps block the same use case: **"I kicked off a run five minutes ago, is it working, and what is it doing right now?"** The user needs visible progress, an operator kill-switch, a correct paused-stage flow, and an aggregated cost/token view to reason about production behavior. This change closes Phase 8 of the wrap-up checklist as a single umbrella initiative so that the run detail page, the paused-stage fix, and the new Observability Tab ship against one consistent data model and one set of API contracts.

## What Changes

### Run detail page rewrite (addresses 8.1, 8.2, 8.3)
- **DAG graph replaces the linear log as the primary view.** Uses `@xyflow/react` + `@dagrejs/dagre` (already in `web/package.json`, currently unused). Nodes colored by state (idle / running-pulse / completed / failed / paused). The existing event/turn log moves to a collapsible drawer that opens when a node is clicked.
- **New REST endpoint** `GET /api/runs/{run_id}/graph` returns `{nodes: [{id, name, role, status, started_at, finished_at, output_preview}], edges: [{from, to, kind}]}`. Built by joining the pipeline YAML definition with the `agent_runs` + `workflow_runs` rows for this run. Pure read; no DB writes.
- **Pause and cancel controls** on the run detail header:
  - `POST /api/runs/{run_id}/pause` — sets `abort_signal` on the currently executing node's AgentState and flips `workflow_runs.status` to `paused`. The node's in-flight LLM call is allowed to complete (documented limitation — see design.md Decision 2).
  - `POST /api/runs/{run_id}/cancel` — sets abort, flips status to `cancelled`, cascades cancel to any running sub-agent tasks owned by the run.
  - Frontend surfaces these as two buttons in the run detail header; `/resume <run_id>` remains the resumption path and is unchanged.
- **Fix the paused-stage button bug** (8.3). Root cause to be confirmed during apply, but the suspected source is the front-end calling the legacy `/resume` text-command endpoint via the chat bus instead of a first-class `POST /api/runs/{run_id}/resume` REST endpoint — the bus path returns nothing to the UI so the UI assumes the click failed and does not reflect the status change. Solution: add `POST /api/runs/{run_id}/resume` taking `{action: "approve"|"reject"|"edit", feedback?: string, edited?: string}` and rewire the paused-stage buttons to it.
- **Formalize the approve semantics** (8.3 design decision). `action="approve"` SHALL NOT carry user feedback into downstream prompts — the existing `src/engine/graph.py:218` behavior (which clears `review_feedback`) is the contract, not an accident. The approve button in the UI therefore has no comment input field; users who want to leave an annotation use the reject or edit paths.

### Observability Tab (addresses 8.7 with i + ii + iii combined)
- **New route** `/projects/:id/observability` under the project dashboard, with three sub-tabs:
  - **Sessions** (ii): list of `chat_sessions` for this project, click-through to a turn-level timeline of one session (horizontal time axis, one row per agent_turn, columns for tokens / duration / tool calls / status). Reuses the telemetry-collection data already available via `/api/telemetry/sessions`.
  - **Aggregates** (iii): recharts line + bar charts for cost_usd, total_tokens, turn_count, error_rate over 24h / 7d / 30d windows. Reuses `/api/telemetry/aggregate?project_id=&window=`.
  - **Raw Timeline** (i): scrollable cross-session agent_turn timeline with role + status filters. Reuses `/api/telemetry/turns?project_id=&limit=&role=&status=`.
- **No new charting library.** Everything uses the existing `recharts` dependency already in `web/package.json`.
- **New backend endpoints only where existing ones fall short.** The proposal assumes `/api/telemetry/*` already emits what the tab needs; during apply we add filter params or small variants on a per-tab basis rather than designing a new API layer.

### Cost pipeline repair (addresses 8.6)
- **Investigate and fix the cost_usd=0 symptom.** `src/telemetry/pricing.py` already implements `calculate_cost` correctly and `config/pricing.yaml` ships entries for 11 provider/model pairs. The most likely root cause is a string mismatch — either the adapter records `provider="openai_compat"` while pricing.yaml uses `provider="openai"`, or the aggregation query in `src/telemetry/query.py` zeroes out costs in a sum that ignores `None` differently than the per-event read. First task on apply is runtime inspection of a completed run's `agent_turns.metadata` to confirm which side is wrong; fix is expected to be a one-line string fix or a small pricing-table addition.
- **Explicitly in scope for this change** per user request, even though it is cross-cutting — the Observability Tab would show all-zero cost charts otherwise, undermining the entire feature.

### Pipeline-interrupt spec tightening (addresses 8.4, 8.5)
- **Formalize the approve/reject/edit contract.** The existing spec (`openspec/specs/pipeline-interrupt/spec.md`) describes the graph plumbing but does not pin down the three-way semantics of `resume_pipeline` feedback. This change adds scenarios making explicit:
  - approve → `review_feedback=""` (no feedback reaches downstream agents)
  - reject → output cleared, feedback written to `review_feedback`, `{node}_run` re-executes with feedback in its prompt
  - edit → output replaced with user-provided text, `review_feedback=""`, graph proceeds as if approved
- **Pin the review-output format** (8.4). Interrupt payloads carry `{node, output}` where `output` is the string produced by the interrupted node. In all three shipped pipelines (`blog_with_review`, `courseware_exam`, `blog_generation`) the string is markdown-shaped, but the pipeline engine does not enforce that — it just forwards the node's `output` field verbatim. The spec documents the "markdown by convention, opaque string by contract" position so front-end renderers can safely apply `react-markdown` while tolerating non-markdown content.
- **Export-freshness scenario** (8.5). Add a scenario stating that `GET /api/runs/{run_id}/export` SHALL return the `final_output` from the most recent `workflow_runs.metadata.final_output` write — i.e., after a reject→re-run→approve cycle, export must serve the latest run's content, not a stale snapshot. `src/export/exporter.py` already implements this correctly by reading directly from `workflow_runs` rather than any cache, but the contract was never pinned in the spec, so a future optimization could silently break it.

## Capabilities

### New Capabilities

- `run-dag-visualization`: DAG-based run detail view — data contract for `GET /api/runs/{run_id}/graph`, node state transitions, click-through behavior, and front-end rendering using `@xyflow/react`.
- `run-ops-controls`: pause / cancel / resume REST API for running pipelines — `POST /api/runs/{run_id}/pause`, `POST /api/runs/{run_id}/cancel`, `POST /api/runs/{run_id}/resume` (first-class replacement for the bus `/resume` path).
- `project-observability-tab`: project Dashboard → Observability route with three sub-tabs (Sessions, Aggregates, Raw Timeline), charting contract for recharts, and any new filter parameters on `/api/telemetry/*` that the tabs need.

### Modified Capabilities

- `pipeline-interrupt`: formalize the approve / reject / edit semantics including the no-feedback-on-approve rule, pin the review-output payload format as an opaque string (markdown by convention), and add the export-freshness scenario.
- `telemetry-collection`: fix the provider/model label mismatch that causes `cost_usd` to be 0 in aggregated views, and add a scenario asserting that non-null per-event costs are preserved through aggregation.
- `web-frontend`: run detail page replaces the linear log with the DAG view as the primary surface, adds pause/cancel header controls, rewires the paused-stage approve/reject/edit buttons to the new `POST /api/runs/{run_id}/resume` endpoint, and adds the Observability route to the project dashboard navigation.

## Impact

### Code
- **Backend**: `src/api/runs.py` grows pause/cancel/resume/graph endpoints (~200 lines); `src/telemetry/pricing.py` or `src/llm/router.py` gets the label-mismatch fix (~10 lines); `src/engine/pipeline.py` gains a cancel path that cascades to sub-agent tasks.
- **Frontend**: `web/src/pages/RunDetailPage.tsx` is significantly rewritten (DAG view + drawer + new header controls); new `web/src/pages/ObservabilityPage.tsx` (~500 LOC across three sub-tab components); new `web/src/components/RunGraph.tsx` wrapping `@xyflow/react`; new API client methods in `web/src/api/`.
- **Specs**: 3 new, 3 modified (see Capabilities above).

### APIs
- **New**: `GET /api/runs/{run_id}/graph`, `POST /api/runs/{run_id}/pause`, `POST /api/runs/{run_id}/cancel`, `POST /api/runs/{run_id}/resume`.
- **Possibly extended** (deferred to apply-time inspection): filter params on `/api/telemetry/sessions`, `/api/telemetry/aggregate`, `/api/telemetry/turns`.
- **Existing `/resume <run_id>` bus command path remains unchanged** — it is still the external-chat entry point for resumption and continues to call the same underlying `src.engine.pipeline.resume_pipeline`.

### Dependencies
- **Zero new runtime dependencies.** `@xyflow/react`, `@dagrejs/dagre`, and `recharts` are already declared in `web/package.json`. This is a deliberate "reuse what's installed" decision per user directive.

### Data model
- **No schema changes.** Every new surface reads from existing tables (`workflow_runs`, `agent_runs`, `agent_turns`, `chat_sessions`) and the pipeline YAML definitions on disk.

### Non-goals
- No real-time WebSocket push for DAG node updates — the existing SSE stream on `/api/runs/{run_id}?stream=true` is sufficient and remains the data source.
- No cross-project aggregated observability view; this change is strictly per-project.
- No changes to the telemetry data model or event schema; only label-normalization and aggregation-query fixes.
- No new charting library; no Langfuse / LangSmith integration.
- No retroactive cost backfill for runs that were emitted before the label fix — historical rows with `cost_usd=null` stay null; the fix applies forward.
