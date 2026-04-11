## Context

Phase 6.1 landed the REST API + SessionRunner registry. Every layer below it already produces the raw signal we need for observability — `LLMResponse.usage` has token counts, `ToolResult` has timing/success, `StreamEvent` has end-of-turn markers, `spawn_agent` has parent/child relationships, `pipeline_event_streams` has node transitions — but none of it is persisted for analysis. The system is rich in transient state and poor in history.

Phase 6.2 of the master plan is "Telemetry 采集". Phase 6.4 (Web management UI) is designed around six visualizations that all depend on telemetry being present: A1 Gantt timeline, A2 token-by-agent pie, A3 tool-call table, A4 LLM-call detail, A5 error panel, A6 execution-flow tree — plus cost views B1–B5 and operational views C1–C3. No telemetry → no UI.

Design discussion with user (2026-04-11) established the event taxonomy (8 types), the three new linking fields (`turn_id`, `parent_turn_id`, `spawn_id` + `spawned_by_spawn_id`), the preview-length approach (30-char default, configurable, stored truncated, full history lives in `Conversation.messages`), and the single-table polymorphic JSONB storage model.

Relevant existing modules and their current shape:
- `src/agent/loop.py::agent_loop` — already has `LLMResponse.usage` at every LLM boundary, already yields `StreamEvent` of type `usage`
- `src/hooks/runner.py` — `PostToolUse` hook already fires after every tool execution with access to `ToolResult`
- `src/engine/session_runner.py` — per-session long-running task, clear turn boundaries at `notify_new_message` / `done` fan-out
- `src/agent/tools/spawn_agent.py` — the sole path for parent→child agent relationships in autonomous mode
- `src/engine/pipeline.py` — already publishes to in-process `_pipeline_event_streams` registry at node boundaries (used by SSE)

Relevant context docs:
- `.plan/claw_design_notes.md` — channel layer and SessionRunner architecture (source of truth for runner flow)
- `.plan/rest_api_deployment_risks.md` — single-process assumptions (telemetry writer task lives in the same process for now)
- `openspec/specs/session-runner/spec.md` — runner lifecycle, subscriber fan-out, persistence contract
- `openspec/specs/hook-events/spec.md` — hook event taxonomy, decides where tool_call emission lives

## Goals / Non-Goals

**Goals:**

1. Capture enough data to support all six Phase 6.4 Run-detail visualizations (A1–A6), all five cost views (B1–B5), and the three operational views (C1–C3). No Phase 6.4 visualization should require a data source we haven't captured.
2. Zero structural change to agent / tool / pipeline core code. All emission points are surgical: one line at an existing event boundary, reading state that already exists.
3. Reconstruct the full execution tree of an autonomous run from a single `WHERE run_id = ? OR session_id = ?` query — no N+1, no recursive fetches.
4. Telemetry writes must not block or slow the agent hot path. Batched async writer with configurable flush.
5. Cost is a first-class field on `llm_call` events (`cost_usd`), calculated at record time from a snapshotted pricing table. Raw tokens are also stored for re-costing if pricing changes.
6. Disabling telemetry (`TelemetryConfig.enabled = False`) is a true zero-overhead path: `collector.record_*()` becomes a no-op function pointer.

**Non-Goals:**

1. **External APM / OTel integration.** No Jaeger, no Datadog, no OpenTelemetry exporter. All data stays in PG; exporters can be layered on later without touching the collector.
2. **Alerting.** Thresholds, alert rules, Slack/email webhooks — all out. Phase 7 at earliest.
3. **Multi-process aggregation.** Single-process assumption holds (same as SessionRunner registry). A multi-process telemetry service would need Redis aggregation or a shared writer; deliberately deferred.
4. **Retroactive re-costing.** When `pricing.yaml` changes, existing events keep the `cost_usd` they had at record time. A re-cost job is easy to add later but is out of scope.
5. **Raw LLM prompt / response storage at the `llm_call` level.** Too much payload bloat, too much PII exposure, and the source of truth is `Conversation.messages` anyway. Preview lives only at `agent_turn` granularity.
6. **Log streaming / tailing endpoints.** Telemetry is a query API (snapshots at rest), not a live stream. Live observation during a run uses the existing SSE `/api/sessions/{id}/events` path.
7. **Arbitrary user-defined custom events.** Event types are closed; 8 types cover the plan. Plugin event types are a future consideration.

## Decisions

### Decision 1 — Single table, polymorphic JSONB payload

**Choice**: One `telemetry_events` table with common columns (`id bigserial`, `ts timestamptz`, `event_type text`, `project_id int`, `run_id text NULL`, `session_id int NULL`, `agent_role text NULL`, `payload jsonb NOT NULL`) plus a GIN index on `payload` and B-tree indexes on `(run_id, ts)`, `(session_id, ts)`, `(event_type, ts)`, `(project_id, ts)`.

**Alternatives considered:**

- **One table per event type** (`llm_calls`, `tool_calls`, `agent_turns`, ...). Rejected: A6 execution tree needs to join across event types. Single-table single-query is much simpler; JSONB indexing in PG 16 is fast enough for Phase 6 scale (target: 1M events per project).
- **Separate `tokens` / `costs` columns at top level** for faster aggregation. Rejected: premature. Views B1–B5 can use JSONB expression indexes if they get slow; adding columns later is a trivial migration.
- **Event-sourcing style with denormalized aggregates**. Rejected: three times the code for no measurable query speedup at our scale.

**Why**: JSONB gives us flexible event shapes without a 9-table schema. `event_type` filtering is a B-tree hit, `payload->>'turn_id'` lookups are GIN hits. Single query path for A6 tree build is the decisive factor.

### Decision 2 — `contextvars` for turn_id / parent_turn_id / spawn_id propagation

**Choice**: Three contextvars defined in `src/telemetry/collector.py`:
- `current_turn_id: ContextVar[str | None]` — set by `SessionRunner` at turn entry
- `current_spawn_id: ContextVar[str | None]` — set by `spawn_agent` tool when emitting its spawn event; child agent inherits via async task context
- `current_run_id: ContextVar[str | None]` — set by `pipeline.py` at pipeline start for the subgraph of events that belong to that run

Collector methods read these contextvars at emit time and merge them into the event payload automatically. Agent loop / tool runner / hook runner never pass `turn_id` explicitly.

**Alternatives considered:**

- **Explicit `turn_id` parameter threaded through `agent_loop`, `ToolRuntime`, `HookRunner`.** Rejected: would add a parameter to a dozen signatures across three layers. High blast radius, fragile — any code path that forgets to thread it loses linking. Contextvar is zero-friction.
- **Store `turn_id` on `AgentState`**. Rejected: AgentState is the agent's own context; polluting it with telemetry identifiers couples the two systems and breaks when sub-agents spawn (they have their own AgentState).
- **Use Python `asyncio.current_task()` attributes**. Rejected: fragile, task identity changes when work is offloaded to executors or gather; contextvars survive exactly that.

**Why**: contextvars are the Python-idiomatic way to carry ambient context across async boundaries. Sub-agents spawned via `asyncio.create_task` inherit the parent's contextvar snapshot at task creation — this is exactly the semantics we need for parent_turn_id → child_turn_id linking. Zero parameter plumbing.

**Caveat**: contextvars propagate *on task creation*, not across `run_in_executor` boundaries. Tool execution already runs inside the event loop (or via `ToolRuntime.run_threadsafe` which we control), so this is fine. If we ever move tools to `ProcessPoolExecutor`, telemetry linking at that boundary will need explicit passing — noted in Open Questions.

### Decision 3 — `agent_turn` is the primary tree node; `llm_call` and `tool_call` are child leaves

**Choice**: The A6 execution-flow tree is rooted at `agent_turn` events. Every `llm_call` / `tool_call` / `agent_spawn` event has a `parent_turn_id` pointing to the `agent_turn` it occurred inside. `agent_spawn` additionally has a `spawn_id`; the first `agent_turn` of the spawned child carries `spawned_by_spawn_id` pointing back.

Tree reconstruction algorithm (pure client-side, no recursive SQL):

```python
events = fetch_events(run_id=..., session_id=...)  # single SELECT
turns = {e["payload"]["turn_id"]: e for e in events if e["event_type"] == "agent_turn"}
children_of: dict[turn_id, list[event]] = defaultdict(list)
spawned_children: dict[turn_id, list[turn_id]] = defaultdict(list)

for e in events:
    if e["event_type"] == "agent_turn":
        parent_spawn = e["payload"].get("spawned_by_spawn_id")
        if parent_spawn:
            # find which turn emitted this spawn
            parent_turn = find_turn_that_emitted_spawn(parent_spawn)
            spawned_children[parent_turn].append(e["payload"]["turn_id"])
    elif e["payload"].get("parent_turn_id"):
        children_of[e["payload"]["parent_turn_id"]].append(e)

# render tree starting from turns with no parent
roots = [t for t in turns.values() if not t["payload"].get("spawned_by_spawn_id")]
```

**Alternatives considered:**

- **Flat event list sorted by timestamp, client infers tree from `agent_role` and `ts` adjacency**. Rejected: ambiguous whenever two agents run in parallel (autonomous mode with concurrent spawned children).
- **Materialized closure table** (`telemetry_tree_closure`). Rejected: premature; client-side tree build is microseconds on 300-event runs.
- **Recursive CTE (`WITH RECURSIVE`)**. Rejected: works but clients that want Gantt view A1 need flat-list access anyway, and the two tree variants (parent_turn for inline events, spawn linkage for sub-agents) complicate recursive SQL more than it's worth.

**Why**: The linking model (`turn_id` / `parent_turn_id` / `spawn_id` / `spawned_by_spawn_id`) carries all the tree structure in plain fields. A single `SELECT ... ORDER BY ts` gets everything; the Python tree builder is 30 lines. Matches how CC's `Task` tree rendering works internally.

### Decision 4 — Preview strings are recorded truncated; pricing is snapshotted at record time

**Choice**:

- `agent_turn.input_preview` / `output_preview`: truncate to `TelemetryConfig.preview_length` (default 30) **at record time**. The full text stays in `Conversation.messages`. The UI links to a session-manager endpoint (`GET /api/sessions/{id}/messages?around_ts=...`) for the "expand full message" interaction.
- `llm_call.cost_usd`: calculated at record time using the `PricingTable` loaded at collector construction. Old events keep their original `cost_usd` — this is **intentional**, for cost auditability.
- `config/pricing.yaml` is a **plain, human-editable yaml** with a documented schema. Adding a new model is a one-line yaml edit. The collector also exposes a `reload_pricing()` method (and a `POST /api/admin/telemetry/reload-pricing` endpoint) so operators can pick up price changes **without restarting the server** — the reload atomically swaps in a fresh `PricingTable`; in-flight events finish with whichever table their thread saw. New events after the swap use the new prices; persisted events are untouched (no retroactive re-costing).

**Alternatives considered:**

- **Store pointers to `Conversation.messages` entries instead of previews**. Rejected: breaks when messages get compacted / deleted in future phases. Telemetry must be a self-contained snapshot.
- **Store full raw content on `agent_turn`**. Rejected: payload bloat. A 50-turn run with 5KB assistant messages would be 500KB of telemetry JSONB per run.
- **Calculate cost lazily at query time**. Rejected: requires joining every `llm_call` query against the pricing table, requires the table to be versioned, and loses "what did this actually cost at the time" auditability.
- **Store both `cost_usd` and pricing-table-version-id** for retroactive re-cost. Rejected for now: adds complexity, and re-costing is an explicit non-goal. A future migration can add the version column if needed.

**Why**: Telemetry is an immutable snapshot at capture time. Everything about an event should be frozen as-of-record. This matches the "ledger" mental model (append-only, no rewrites) and makes cost reporting auditable.

### Decision 5 — Batched async writer with bounded queue + fire-and-forget emission

**Choice**: `TelemetryCollector` exposes `record_*` methods that are sync (synchronous append to an in-memory queue). A background asyncio task (`_writer_loop`) drains the queue every `flush_interval_sec` (default 2s) or when it hits `batch_size` (default 100), whichever comes first. The queue is bounded at `max_queue_size` (default 10000); if full, the collector drops the oldest event and logs a WARNING.

```python
def record_llm_call(self, ...):
    if not self._enabled:
        return
    event = self._build_llm_call_event(...)
    try:
        self._queue.put_nowait(event)
    except asyncio.QueueFull:
        self._drop_oldest_and_insert(event)
```

**Alternatives considered:**

- **Synchronous per-event PG INSERT**. Rejected: blocks agent loop on DB latency. A run with 50 LLM calls × 5 tool calls = 250 events = 250 round-trips to PG ≈ seconds of wall time added to hot path.
- **Async per-event write with `await db.execute(...)`**. Rejected: still adds DB round-trip latency per event, even if it doesn't block other coroutines. Batching is free throughput.
- **Write to Redis stream first, separate consumer writes PG**. Rejected: two-system persistence, Redis becomes a single-point-of-failure for durability, adds operational complexity. PG is already the source of truth.
- **Fsync-on-crash via write-ahead log file**. Rejected: massive over-engineering for analytics data; losing the last 2 seconds of telemetry on crash is acceptable (logged as a known loss window).

**Why**: Agent hot path stays synchronous and fast. DB batching amortizes overhead. Bounded queue with oldest-drop is the right back-pressure behavior — telemetry is analytics data, not ledger-critical; losing events under extreme load is strictly better than stalling agent execution.

**Crash loss window**: Up to `flush_interval_sec` (2 seconds) of events can be lost on SIGKILL. FastAPI lifespan shutdown drains the queue gracefully on SIGTERM. Acceptable trade-off — telemetry is analytics, not an audit log.

### Decision 6 — Telemetry emission is off-by-switch, not off-by-import

**Choice**: `TelemetryCollector.enabled` is a runtime flag. When disabled, all `record_*` methods return immediately after a single bool check. The collector object and all emission call sites still exist; they just do nothing. Tests that don't care about telemetry construct a `NullTelemetryCollector` (or pass `enabled=False`) and the hot path is unchanged.

**Alternatives considered:**

- **Conditional imports / feature flags at module level**. Rejected: makes code harder to reason about, and makes disabling telemetry for a single test awkward.
- **Dependency injection of a Protocol type**. Rejected: more ceremony for the same effect. Simple boolean gate is enough.
- **Separate "real" and "null" subclasses as separate classes with a factory**. Considered — this is what we actually do for tests (`NullTelemetryCollector`), but production runtime uses the boolean flag. Tests get clean construction, production gets a single hot-path branch.

**Why**: Keeps call sites uniform (`collector.record_llm_call(...)` always). Lets us turn telemetry off cheaply for tests, local dev, or emergency disable without redeploying code.

### Decision 7 — Event emission lives in existing "natural" boundaries, not as new hook types

**Choice**: Each event type has exactly one emission site, chosen to be the place where the data already exists:

| Event | Emission site | Why there |
|---|---|---|
| `llm_call` | `src/agent/loop.py` after each `call_llm()` response | `LLMResponse.usage` is available; adding a new hook type for this would duplicate work |
| `tool_call` | `src/hooks/runner.py` `PostToolUse` path | PostToolUse hook already has `ToolResult` + timing; we're just piggybacking on an existing event, not creating a new concept |
| `hook_event` | `src/hooks/runner.py` hook dispatcher | Immediately after each hook returns — this is a new event type but stays within the hook runner file |
| `agent_turn` | `src/engine/session_runner.py` turn entry / exit | Only place that knows "a turn is starting/ending"; also the place that owns contextvar setup |
| `agent_spawn` | `src/agent/tools/spawn_agent.py` | Only place that sees parent→child relationship |
| `pipeline_event` | `src/engine/pipeline.py` at node boundaries | Already has `_pipeline_event_streams` — we either subscribe as a consumer or emit inline. Inline is simpler and doesn't compete with SSE consumers |
| `session_event` | `src/engine/session_runner.py` lifecycle hooks | Only place that knows session creation / idle exit / max_age exit |
| `error` | Wrapped at every emission site above — each try/except that catches the error converts it to an `error` event before re-raising | No single "error boundary" exists; each layer catches its own |

**Alternatives considered:**

- **Introduce new hook types** (`OnLLMCall`, `OnTurnStart`, `OnTurnEnd`, `OnError`) and plug telemetry in as a hook handler. Rejected: adds a new abstraction, and the hook system's raison d'être is user-configurable permission decisions — telemetry is not user-configurable. Wrong tool for the job.
- **AOP / decorator-based injection** around `call_llm`, `tool.run`, `agent_loop`. Rejected: obscures flow, harder to grep, harder to test.
- **Centralized event bus** (like nanobot's MessageBus). Rejected: we already have MessageBus for channel I/O and `_pipeline_event_streams` for pipeline SSE. A third eventing system just for telemetry is unjustified duplication.

**Why**: Direct inline emission at data boundaries is the simplest code; grep-able; zero runtime indirection. Each touched file gets 1-3 lines; no existing abstraction is perturbed.

## Risks / Trade-offs

1. **[Risk] Batch writer loses up to 2s of events on SIGKILL / crash.**
   → **Mitigation**: Documented as the known loss window. FastAPI lifespan drain on SIGTERM covers graceful shutdown. Acceptable because telemetry is analytics-grade, not audit-grade. If a stronger guarantee is needed later, switching to per-event write (or a WAL file) is a collector-internal change.

2. **[Risk] Contextvar propagation breaks if we ever run tools in a process pool or hand work to a sync executor.**
   → **Mitigation**: Noted in Open Questions. Current tool execution stays in the event loop (or `run_threadsafe` which we control). If we move to `ProcessPoolExecutor`, the collector will need explicit context passing (one extra parameter at the boundary). Not solving now.

3. **[Risk] JSONB query performance at scale (>1M events per project).**
   → **Mitigation**: GIN index on `payload` + B-tree indexes on `(run_id, ts)` / `(session_id, ts)` / `(event_type, ts)`. Phase 6 target is 1M events/project; PG 16 JSONB + GIN handles this range well. If aggregate queries get slow, we can add expression indexes on hot JSONB paths (`(payload->>'cost_usd')::numeric`) without schema migration. Worst case, materialized views of common aggregates.

4. **[Risk] Pricing table drift — if `pricing.yaml` is out of date, `cost_usd` is wrong.**
   → **Mitigation**: `pricing.yaml` ships with default prices and is versioned in git. Adding a new model requires a one-line edit. Missing model → collector logs WARNING on first use and stores `cost_usd = None` (queries treat None as "unpriced"). Users can edit the yaml to fix without a code change, and call `POST /api/admin/telemetry/reload-pricing` to pick up the change without restarting.

5. **[Risk] `input_preview` / `output_preview` may leak PII if users post sensitive data to the bot and then we display those previews in a shared dashboard.**
   → **Mitigation**: 30-char default is the first layer of defense (not enough for credit card numbers, SSNs, etc.). Operators can set `preview_length = 0` to disable previews entirely. Full mitigation is an access-control decision at the REST API layer — telemetry endpoints must respect project-level permissions (already true for `/api/projects/*`). Documented as an operator consideration.

6. **[Risk] Agent loop adds one function call per LLM invocation even when telemetry is disabled.**
   → **Mitigation**: `collector.record_llm_call()` first line is `if not self._enabled: return`. Cost is a single attribute access and a bool check — sub-microsecond. Negligible compared to the LLM call itself.

7. **[Risk] `spawn_id` contextvar inheritance might leak across concurrent spawned children if parent spawns two children in parallel.**
   → **Mitigation**: Each spawn generates its own `spawn_id`, and `asyncio.create_task` snapshots the contextvar at creation time. Two concurrent spawns produce two distinct task contexts with different `spawn_id`s — this is the standard contextvar behavior. Verified in `test_telemetry_spawn_linking` (to be written).

8. **[Risk] `telemetry_events` table grows unbounded; no retention policy.**
   → **Mitigation**: Out of scope for this change, but noted as a Phase 7 follow-up. Retention can be a scheduled `DELETE WHERE ts < now() - interval '90 days'` job; partitioning by `ts` becomes relevant at >10M events per project.

## Migration Plan

No data migration. Deploy as a code change:

1. Apply schema: `scripts/init_db.sql` adds `telemetry_events` table + indexes.
2. Ship `config/pricing.yaml` with default pricing for Anthropic / OpenAI / DeepSeek / Qwen.
3. Deploy code; collector starts in FastAPI lifespan startup, drains on shutdown.
4. Rollback: Set `TelemetryConfig.enabled = False` in settings — zero code change needed. Data in `telemetry_events` is preserved (a later re-enable resumes capture cleanly). Full rollback: revert commit, leave the table in place (unused table is harmless).
5. Verification: Trigger a blog pipeline run + a chat turn, then `SELECT COUNT(*) FROM telemetry_events WHERE run_id = ?` should return non-zero for the pipeline and `SELECT ... WHERE session_id = ?` for the chat turn.

## Open Questions

1. **Contextvar propagation across `ProcessPoolExecutor` boundaries** — if/when Phase 7 introduces sandboxed tool execution in subprocesses, telemetry linking will need explicit passing. Not solving now; flagging for Phase 7 design review.
2. **Retention policy** — 90-day rolling default? Per-project override? Out of scope; Phase 7 or as-needed follow-up.
3. **Visualization layer caching** — should `telemetry_query` functions cache expensive aggregate queries (e.g. weekly cost trends) via Redis? Leaning no for Phase 6.2; reconsider if Phase 6.4 UI shows latency issues.
4. **Error event capture at the MessageBus gateway layer** — the bus path has its own top-level try/except in `Gateway._process_message`. Should that path emit an `error` event? Leaning yes but deferring the exact call site to implementation review.
