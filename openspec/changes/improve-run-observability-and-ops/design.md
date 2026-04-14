## Context

Phase 8 of the wrap-up checklist bundles four symptoms that all trace back to one missing capability: **an operator view that answers "what is this run doing right now?"** The run detail page (`web/src/pages/RunDetailPage.tsx`, 1461 LOC) renders a flat, scrolling agent-turn log. There is no graph, no pause, no cancel, and the paused-stage approve/reject/edit buttons are visibly broken — clicking them appears silent even though the backend resumes successfully. Separately, the project Dashboard has no observability surface at all, so the working `/api/telemetry/*` endpoints and the 11-entry `config/pricing.yaml` pricing table are effectively invisible: every run's `cost_usd` column shows 0 in the UI even when the backend would compute a real number.

The key constraints shaping this design:

1. **Zero new runtime dependencies.** `@xyflow/react`, `@dagrejs/dagre`, and `recharts` are already declared in `web/package.json` and currently unused for this purpose. The user directive is "reuse the framework you already have."
2. **No schema changes.** Everything reads from existing tables (`workflow_runs`, `agent_runs`, `agent_turns`, `chat_sessions`) and the pipeline YAML on disk.
3. **LangGraph interrupt/resume is the existing substrate.** The pause/cancel controls must not introduce a second control plane; they must layer cleanly on top of the `interrupt_fn` / `resume_pipeline` path that already exists in `src/engine/graph.py` and `src/engine/pipeline.py`.
4. **Backward compatibility with the `/resume <run_id>` bus command.** That path is still used by third-party chat (Discord/QQ/WeChat) clawbot operators and cannot be removed or broken.
5. **Investigation over speculation for the cost bug.** The pricing code is correct and the YAML is populated — the bug is almost certainly a label-mismatch between adapter emission and pricing-table keys, but the exact string is unknown until we inspect a completed run at apply time.

This change is a single umbrella initiative, not four separate changes, because all four symptoms share one data model (run → node → turn → telemetry event) and one set of UI surfaces. Splitting them would force the shared data contract (`GET /api/runs/{run_id}/graph`, node status vocabulary, telemetry filter params) to be designed twice or fought over between two in-flight changes.

## Goals / Non-Goals

**Goals:**

- **Make running pipelines legible.** A user opening a run detail page sees the DAG, sees which node is executing, and can tell within 2 seconds whether the run is healthy, stuck at an interrupt, or failed.
- **Give operators a kill switch.** Pause and cancel are first-class REST endpoints on `/api/runs/{run_id}/*`, not special bus commands, so the web UI can wire them to buttons without touching the chat bus.
- **Fix the paused-stage button silence** so the approve/reject/edit workflow for `blog_with_review` and similar interrupt-bearing pipelines actually works from the web UI.
- **Pin down the three-way review semantics in spec form** so that approve = "no feedback forwarded", reject = "re-run with feedback", edit = "replace output and proceed" is enforced by spec and not just by an accidental line of code in `graph.py`.
- **Repair the cost pipeline end-to-end** so that `cost_usd` is populated on new runs and aggregated correctly by `/api/telemetry/aggregate`, enabling the Observability Tab to render non-zero charts.
- **Deliver a per-project Observability Tab** covering Sessions (per-session turn timeline), Aggregates (cost/tokens/errors over time windows), and Raw Timeline (cross-session agent_turn feed), all reusing `recharts` and the existing `/api/telemetry/*` endpoints.
- **Pin the export-freshness contract** so that exported final_output is always the latest `workflow_runs.metadata.final_output`, even after a reject → re-run → approve cycle.

**Non-Goals:**

- **Real-time WebSocket push for DAG node updates.** The existing SSE stream at `/api/runs/{run_id}?stream=true` is sufficient and remains the data source; the DAG re-renders when SSE events arrive. Not adopting WebSocket avoids a new transport layer.
- **Cross-project observability aggregation.** This change is strictly per-project. A "tenant overview" dashboard is out of scope.
- **New charting library or new graph library.** Everything uses what `web/package.json` already lists. No Langfuse, no LangSmith, no ReactFlow alternative.
- **Telemetry event schema changes.** The fix for `cost_usd=0` is label normalization and aggregation-query correction, not a new event shape.
- **Retroactive cost backfill.** Historical `agent_turns` rows with `cost_usd=null` stay null. The fix applies to events emitted after the label normalization ships. (Explicit user direction: "no migration.")
- **Interrupt-mid-LLM-call.** LangGraph's pause semantics allow the currently executing LLM call on the active node to finish before the pause takes effect. We accept this as a documented limitation — a hard mid-call abort would require killing the HTTP connection at the provider layer, which is out of scope and would leave the conversation in an inconsistent state.
- **Autonomous coordinator UI changes.** This change only touches pipeline run surfaces. Autonomous-mode sessions have their own run list but do not grow a DAG view in this change.

## Decisions

### Decision 1 — DAG data contract: a single flat read endpoint

**Choice:** `GET /api/runs/{run_id}/graph` returns a flat `{nodes, edges}` payload built by joining the pipeline YAML definition (from `pipelines/*.yaml`) with the live `workflow_runs` + `agent_runs` rows for this run.

```json
{
  "run_id": "run_abc123",
  "pipeline": "blog_with_review",
  "status": "paused",
  "nodes": [
    {
      "id": "planner",
      "name": "planner",
      "role": "researcher",
      "status": "completed",
      "started_at": "2026-04-14T10:00:12Z",
      "finished_at": "2026-04-14T10:00:47Z",
      "output_preview": "Plan: 3-section outline on..."
    },
    {
      "id": "editor",
      "name": "editor",
      "role": "writer",
      "status": "paused",
      "started_at": "2026-04-14T10:02:30Z",
      "finished_at": null,
      "output_preview": "Draft v1 ready for review..."
    }
  ],
  "edges": [
    { "from": "planner", "to": "writer", "kind": "sequence" },
    { "from": "writer", "to": "editor", "kind": "sequence" }
  ]
}
```

- **Node status vocabulary** (closed set): `idle`, `running`, `completed`, `failed`, `paused`, `cancelled`, `skipped`.
- **`output_preview`** is the first 200 characters of the node's output field, HTML-safe, for the DAG tooltip. Full content stays in the drawer fetch.
- **Edges are derived from the pipeline YAML,** not from runtime traces. The YAML is authoritative for topology; `agent_runs` provides live state. This means the graph renders correctly even before any node has started.

**Alternative considered:** stream incremental node-state updates via a new WebSocket. Rejected because the existing SSE stream already delivers every state change the DAG needs, and adding a transport is a significant cost. The frontend calls `/graph` once on page load, then listens to SSE and patches node status in place.

### Decision 2 — Pause semantics: abort signal + LangGraph interrupt, never mid-LLM kill

**Choice:** `POST /api/runs/{run_id}/pause` sets `abort_signal` on the currently executing node's `AgentState` and flips `workflow_runs.status` to `paused`. The node's current LLM call is allowed to finish; the loop checks `abort_signal` between turns. This matches how `src/engine/pipeline.py` already handles interrupts — we are layering a user-initiated abort on top of the mechanism that already exists for graph-level interrupts.

**Alternative considered:** a hard mid-call abort (drop the HTTP connection to the provider). Rejected because:
- It leaves `agent_turns` in a partial state that's hard to reason about.
- Providers bill for tokens streamed before the abort anyway.
- It introduces a second abort path in parallel with the LangGraph-native one, doubling the surface area for bugs.

**Consequence (documented as a limitation):** a pause clicked during a long streaming call may take 0–60 seconds to take visible effect. The UI must reflect "pause requested" as distinct from "paused" to avoid user confusion. Node state goes `running → pausing → paused`. (The `pausing` state is UI-only; the backend only persists `paused` once the node actually yields.)

### Decision 3 — Cancel cascades to sub-agent tasks

**Choice:** `POST /api/runs/{run_id}/cancel` sets `abort_signal`, flips `workflow_runs.status` to `cancelled`, and cascades cancellation to any running sub-agent tasks spawned by nodes in this run (via the `spawn_agent` tool). The cascade mechanism: sub-agents carry the parent run_id in their AgentState, and the cancel handler walks the child list and sets abort on each.

**Alternative considered:** cancelling only the currently executing top-level node and letting sub-agents finish. Rejected because a long-running sub-agent (e.g., a deep web_search chain) could keep billing tokens for 30+ seconds after the user clicked cancel, which is exactly the behavior a kill switch is supposed to prevent.

### Decision 4 — Tighten the existing `POST /api/runs/{run_id}/resume` body contract, and re-attach SSE after resume

**Correction from the original proposal:** a code-inspection pass at apply start (investigation task 1.1) revealed that the proposal's root-cause theory was wrong. The relevant facts:

1. `POST /api/runs/{run_id}/resume` **already exists** at `src/api/runs.py:258`, accepting `ResumeBody(value: Any)` and forwarding `body.value` into `resume_pipeline(feedback=...)`.
2. The web UI at `web/src/pages/RunDetailPage.tsx:1330` already calls `client.post('/runs/${runId}/resume', { value })`. It has **never** used the `/resume <run_id>` bus command path.
3. `src/engine/graph.py::interrupt_fn` (lines 181–218) already handles dict-shaped feedback correctly: when the resume value is `{action, feedback?, edited?}`, it dispatches approve / reject / edit exactly as the spec requires.

So the backend and the HTTP shape of the resume call are not the bug. The real root cause of the 8.3 "silent click" symptom is in the frontend: **after a successful resume, the page never re-subscribes to the run's event stream.** The sequence:

```
user clicks Approve
 → client.post('/runs/{id}/resume', {value: {action: 'approve'}})  ✅ 202
 → onResumed() → loadHistorical() — a single GET /runs/{id}
 → but the SSE subscription opened on the live-stream path was already
   torn down in the finally block at RunDetailPage.tsx:702 when the run
   first entered paused state
 → nothing in the UI resubscribes or polls for subsequent transitions
 → the backend successfully runs the next node(s), but no event ever
   reaches the page, so status stays frozen on whatever loadHistorical
   captured in its single read
```

From the user's perspective this looks exactly like "the click did nothing" because the UI is observably inert, even though the backend has advanced past the interrupt and may already have completed or paused at the next node.

**Choice:**

1. **Keep the existing REST endpoint** (`POST /api/runs/{run_id}/resume`). Do NOT introduce a second parallel endpoint.
2. **Tighten the request body contract at the API layer.** Accept both the legacy string form (for backward-compat with any CLI / test callers that pass a bare string) AND the structured `{action, feedback?, edited?}` form. When `action="edit"` is specified, `edited` is required; missing it yields HTTP 422. When `action="approve"`, any `feedback` field is ignored. This replaces the current `Any` body with a validated pydantic discriminated model.
3. **Fix the real 8.3 bug in the frontend: re-attach a run event subscriber after a successful resume.** The mechanism is either (a) keep the SSE stream alive across paused/running transitions instead of tearing it down when status first hits `paused`, or (b) open a short-lived status poll (every 1–2s) after a resume that runs until the run reaches a terminal state. Option (a) is cleaner; option (b) is a fallback if option (a) turns out to have connection-lifetime issues in the existing stream handler.

**Alternative considered:** add a second REST endpoint (`POST /api/runs/{run_id}/resume-v2`) that returns the new run state in the response body, letting the frontend update optimistically without any subscription. Rejected because (a) it duplicates a working endpoint, (b) "return the next state synchronously" is impossible when the next node takes minutes to run, (c) the SSE infrastructure exists for exactly this reason.

**Backward compatibility:** the `/resume <run_id>` bus command path (`src/bus/gateway.py`) remains unchanged. It is a separate code path invoked by external chat channels (Discord/QQ/WeChat clawbot operators) and continues to call `resume_pipeline` directly.

### Decision 5 — Approve semantics: pure binary, no comment input

**Choice:** The approve button in the paused-stage UI has **no** comment input field. `action="approve"` forwards `{review_feedback: ""}` to the graph, matching the existing `src/engine/graph.py:218` behavior. Users who want to attach an annotation use reject (which sends feedback and re-runs the node) or edit (which replaces the output and proceeds).

**Rationale:** the existing backend drops feedback on approve. This is not an accident — it is the only way to make "approve" mean "ship it as-is" without polluting the downstream node's prompt with stale review commentary. If the approve button accepted a comment, the front-end would have to either silently drop it (confusing) or send it (breaking the invariant). The spec pins this behavior so a well-meaning future refactor can't flip it back.

**Alternative considered:** approve-with-optional-comment, where the comment is stored as telemetry metadata but does not reach downstream prompts. Rejected because the user directive was "no comment on approve" and because a non-prompt-reaching comment field is a UI-only affordance that would grow orphaned semantics over time.

### Decision 6 — Observability Tab: three sub-tabs, reuse `/api/telemetry/*` with additive filters only

**Choice:** `/projects/:id/observability` hosts three sub-tabs:

- **Sessions** (ii): list `chat_sessions` where `project_id` matches. Click into one session → horizontal timeline of `agent_turn` rows with columns for tokens / duration / tool_calls / status. Data source: `GET /api/telemetry/sessions?project_id=`.
- **Aggregates** (iii): recharts line chart for cost_usd and total_tokens, bar chart for turn_count and error_rate, over 24h / 7d / 30d windows. Data source: `GET /api/telemetry/aggregate?project_id=&window=`.
- **Raw Timeline** (i): scrollable cross-session `agent_turn` feed with role and status filters. Data source: `GET /api/telemetry/turns?project_id=&limit=&role=&status=`.

**New backend surface is additive only:** the existing `/api/telemetry/*` endpoints already return most of what the tabs need. Where a filter parameter is missing (e.g., `project_id` on `/turns`), we add it as a query-string param, not a new endpoint. No new resource URLs, no new serialization layer.

**Alternative considered:** designing a unified `/api/observability/v1/*` namespace that merges session/aggregate/turn data. Rejected as over-engineering — the three tabs have distinct data shapes and caching needs, and the existing endpoints are already stable. Reusing them is the shortest path.

### Decision 7 — Cost fix: runtime inspection first, then one-line patch

**Choice:** At apply time, the first task is to run a completed pipeline through the stack and inspect an `agent_turns.metadata` row to see what provider/model labels the adapter actually emits. Compare those strings to `config/pricing.yaml` keys. Fix wherever the mismatch is — expected to be one string, in one of three places:

1. `src/llm/router.py` or the concrete adapter (`openai_adapter.py`, `anthropic_adapter.py`, etc.) is emitting the wrong provider label (e.g., `"openai_compat"` instead of `"openai"` for proxied calls).
2. `config/pricing.yaml` is missing a provider/model pair that the router uses in practice.
3. `src/telemetry/query.py` is aggregating cost with a `SUM` that treats `NULL` differently than a per-event read expects (e.g., coercing to 0 at the wrong step).

**The fix is not a rewrite of the cost system.** `src/telemetry/pricing.py::calculate_cost` is correct; the 11-entry table is correct; the collector emission path is correct. This is a label audit, not an architecture change.

**Alternative considered:** defer the cost fix to a separate change. Rejected because the Observability Tab's Aggregates sub-tab would ship with all-zero cost charts, which would undermine the whole feature — the user's explicit request is "bundle the cost fix in." A separate change would mean two UI deliveries where the second one adds the data the first one needed.

### Decision 8 — Interrupt-payload shape: markdown by convention, opaque string by contract

**Choice:** The spec pins the interrupt payload as `{node: string, output: string}` where `output` is the interrupted node's output field verbatim. In all three shipped pipelines (`blog_with_review`, `courseware_exam`, `blog_generation`) this string is markdown-shaped, but the pipeline engine does not enforce markdown — it forwards whatever `output_field` the node wrote. Front-end renderers SHOULD apply `react-markdown` and SHOULD tolerate non-markdown content without crashing. Back-end code MUST NOT assume markdown structure (no header parsing, no table extraction).

**Rationale:** the current code accidentally works because all three pipelines happen to produce markdown. A fourth pipeline that outputs JSON or plain text would surface a latent contract ambiguity. Pinning the contract now prevents a future regression.

**Alternative considered:** require the pipeline engine to enforce markdown (wrap non-markdown strings in a code fence, reject non-string outputs, etc.). Rejected because it adds engine-side validation for a problem that hasn't occurred and would couple the graph layer to a content format.

### Decision 9 — Export-freshness contract: always read the latest `workflow_runs.metadata.final_output`

**Choice:** The spec pins `GET /api/runs/{run_id}/export` as always reading from the most recent write to `workflow_runs.metadata.final_output`. `src/export/exporter.py` already does this correctly (no caching layer), but the contract was never in the spec, so a future optimization could silently break it. After a reject → re-run → approve cycle, the export MUST serve the latest final_output.

**Alternative considered:** add an `export_cache` table keyed by run_id for faster reads. Rejected — there is no evidence of an export-performance problem, and introducing a cache would require invalidation logic on every resume, which is exactly the class of bug this scenario is designed to catch.

### Decision 10 — `PausePending` is a UI-only state, not a DB state

**Choice:** `workflow_runs.status` stays in `{running, paused, cancelled, completed, failed}`. When the frontend clicks pause, it optimistically displays a "pausing..." badge on the active node, but does not write a new status to the DB. Once the backend actually reaches the yield point, the status becomes `paused` and the SSE stream pushes the update, and the badge resolves to the final state.

**Alternative considered:** add a `pausing` status to the DB enum. Rejected because it doubles the state space for a UI affordance that lives for 0–60 seconds and would require migrations on every consumer of `workflow_runs.status`.

## Risks / Trade-offs

**[Risk] Pause may take up to 60 seconds to take visible effect during a long streaming LLM call.**
→ Mitigation: the UI shows a distinct "pausing..." state with a spinner and a tooltip explaining "waiting for the current LLM call to finish." Documented as a known limitation in both the user-facing help text and the spec. Users expecting instant pause are redirected to cancel if they want an immediate stop.

**[Risk] The DAG graph endpoint joins YAML topology with live DB state on every call. For a large pipeline (20+ nodes) this could be slow.**
→ Mitigation: YAML parsing is cached in-process (the pipeline registry already does this). The DB join is a single query over `agent_runs WHERE run_id = ?`, which is indexed. Expected p99 under 50ms for pipelines up to 100 nodes. Revisit if Phase 9 introduces much larger pipelines.

**[Risk] Re-attaching SSE after resume may introduce stream-lifetime bugs (double-subscription, orphan connections, heartbeat races).**
→ Mitigation: the existing `subscribe_pipeline_events` / `unsubscribe_pipeline_events` path in `src/engine/run.py` is already used by the trigger endpoint's streaming branch, so the infrastructure is proven. The frontend change is to delay the finally-block unsubscribe until status is terminal (completed/failed/cancelled), not to introduce a second subscription path. If keeping the connection alive across pause→resume turns out to have connection-idle issues (proxies dropping the stream after 60+ seconds of heartbeat-only traffic), fallback option (b) is a short-lived status poll post-resume — simpler, no stream-lifetime risk, and acceptable since the 24/7 observation case is what SSE is for, not the approve-then-wait case.

**[Risk] Cost label mismatch might be in a place that's hard to fix without a wider rename.**
→ Mitigation: the pricing table accepts arbitrary `provider/model` keys, so the fix can go either in the adapter (normalize at emit time) or in the YAML (add an alias row). Both are one-file changes. A wider rename is explicitly out of scope — if the inspection reveals one, we pause and write a follow-up change.

**[Risk] The Observability Tab uses endpoint-level `project_id` filtering, which assumes the backend query paths filter correctly. If any of the three endpoints has a latent bug (e.g., ignores `project_id` silently), a user could see another project's data.**
→ Mitigation: the apply tasks include an integration test for each endpoint that asserts `project_id=A` never returns rows with `project_id=B`. The test seeds two projects in a real DB, not a mock.

**[Risk] The run detail rewrite is large (1461 LOC → DAG view + drawer).** A big-bang replacement risks losing details that the existing linear log surfaces (e.g., rare error states that only appeared on specific turn types).
→ Mitigation: the drawer preserves the full event/turn log as an expandable section, so no data is lost — it's just behind a click instead of on the main surface. A feature flag is explicitly NOT used; the user directive is "ship one version, no dual code path."

**[Trade-off] Reusing `@xyflow/react` means inheriting its rendering costs (~150KB gzipped, already in the bundle).** For small pipelines (3–5 nodes) the library is overkill compared to hand-drawn SVG. We accept the overhead because (a) the library is already paid for, (b) it handles click/hover/pan for free, and (c) future larger pipelines will benefit.

**[Trade-off] Cascading cancel to sub-agents walks a child list that isn't currently indexed.** For a run with hundreds of sub-agent tasks this could be slow.
→ Accepted: current runs have at most a handful of sub-agent tasks, and the cancel path is not latency-critical (users click cancel once and wait). Revisit if sub-agent fan-out grows.

## Migration Plan

This change is purely additive at the API layer and has no data migrations, so the deployment is straightforward:

1. **Backend**: ship new endpoints (`/graph`, `/pause`, `/cancel`, `/resume`) and the cost label fix. Existing endpoints unchanged.
2. **Frontend**: ship the rewritten `RunDetailPage.tsx` and the new `ObservabilityPage.tsx`. No feature flag — the old linear-log view is replaced in one cut.
3. **Specs**: update `pipeline-interrupt`, `telemetry-collection`, and `web-frontend`; add `run-dag-visualization`, `run-ops-controls`, `project-observability-tab`.
4. **Rollback**: revert the frontend commit — the old `RunDetailPage.tsx` returns. The new backend endpoints can stay (they are additive) or be reverted alongside; they do not affect existing callers.

No DB migrations. No config changes beyond the cost label fix. No new environment variables.

## Open Questions

1. **Exact root cause of the paused-stage button silence.** ✅ Resolved during the apply-start code inspection (see Decision 4 correction). The real cause is frontend SSE tear-down on first paused transition with no re-attach after resume, not the bus-command theory. Design updated in-place; tasks.md rewritten accordingly.
2. **Exact cost label mismatch location.** Resolved at apply time by inspecting a completed run's `agent_turns.metadata`. Three hypotheses listed in Decision 7; apply task will pick one.
3. **Whether the DAG view needs a "compact" layout mode for narrow windows.** Deferred to implementation — we will see how dagre's default layout looks on the real shipped pipelines before deciding if a toggle is needed. Not a spec concern.
4. **Whether `/api/telemetry/aggregate` already supports the 30-day window.** If not, adding it is a small change to the query layer. Confirmed during apply.
