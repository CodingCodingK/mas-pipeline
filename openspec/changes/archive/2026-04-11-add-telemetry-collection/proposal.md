## Why

Phase 6.1 shipped the REST API and SessionRunner registry, but the system currently produces zero persisted telemetry. Every LLM call, tool invocation, agent turn, spawn, pipeline node transition, and error is ephemeral — once a turn finishes, there is no record of what happened, how long it took, how many tokens were consumed, or how much it cost. This blocks:

- **Phase 6.4 UI** (management dashboard), which is designed around telemetry-driven views (Gantt timeline, token pie, cost trends, execution-flow tree). Phase 6.4 cannot start until the data it consumes exists.
- **Cost visibility** for end users, who currently have no way to see the dollar cost of a pipeline run or a conversation turn.
- **Debugging autonomous mode**, where a coordinator may spawn multiple sub-agents across many turns and the only current way to understand "what actually happened" is to tail log files.

This change introduces the telemetry capture layer (Phase 6.2 of the master plan) and its aggregate query API, providing the data foundation for both cost reporting and execution-flow debugging.

## What Changes

- **NEW** `src/telemetry/` module: `TelemetryCollector`, event dataclasses, pricing table, aggregate query functions, FastAPI router.
- **NEW** PG table `telemetry_events` (single-table polymorphic JSONB model, GIN-indexed).
- **NEW** 8 event types: `llm_call`, `tool_call`, `agent_turn`, `agent_spawn`, `pipeline_event`, `session_event`, `hook_event`, `error`.
- **NEW** Three linking fields (`turn_id`, `parent_turn_id`, `spawn_id`) carried via `contextvars` to reconstruct the full execution tree of an autonomous run without touching agent/tool/pipeline core code.
- **NEW** `input_preview` / `output_preview` (30-char default, configurable) on `agent_turn` for A6 flow-tree node display. Truncation happens at record time; full history stays in `Conversation.messages`.
- **NEW** Cost calculation: static `pricing.yaml` table loaded at collector construction, `cost_usd` snapshotted at record time per `llm_call`.
- **NEW** REST endpoints under `/api/runs/{run_id}/telemetry/*` and `/api/sessions/{session_id}/telemetry/*`: summary, timeline, agent rollup, execution-flow tree, cost breakdown, cross-run trends, error list.
- **NEW** Settings: `TelemetryConfig { enabled, preview_length, batch_size, flush_interval_sec, pricing_table_path }`.
- **MODIFIED** `agent-loop`: emits `llm_call` events after each LLM invocation (via collector call, behind a feature flag so disabling telemetry is zero-overhead).
- **MODIFIED** `hook-runner`: `PostToolUse` hook path emits `tool_call` events; hook execution itself emits `hook_event`.
- **MODIFIED** `session-runner`: sets `turn_id` contextvar on turn entry, emits `agent_turn` + `session_event` at turn boundaries.
- **MODIFIED** `spawn-agent`: emits `agent_spawn` event with a generated `spawn_id`; spawned child's first `agent_turn` picks up `spawned_by_spawn_id` from contextvar inheritance.
- **MODIFIED** `pipeline-execution`: subscribes to or emits `pipeline_event` at node boundaries and pause/resume points.

## Capabilities

### New Capabilities
- `telemetry-collection`: Event model, collector, contextvar-based linking, batched PG writer, pricing table, REST aggregate query API. Single capability owning the whole telemetry pipeline end to end.

### Modified Capabilities
- `agent-loop`: adds post-LLM-call telemetry emission hook (one new requirement).
- `hook-runner`: adds `tool_call` and `hook_event` emission from the PostToolUse path (one new requirement).
- `session-runner`: adds `turn_id` contextvar setup and `agent_turn` / `session_event` emission at turn boundaries (one new requirement).
- `spawn-agent`: adds `agent_spawn` event emission with `spawn_id` propagation via contextvar (one new requirement).
- `pipeline-execution`: adds `pipeline_event` emission at node and run boundaries (one new requirement).

## Impact

**New code:**
- `src/telemetry/__init__.py`
- `src/telemetry/events.py` — 8 event dataclasses + union type
- `src/telemetry/collector.py` — `TelemetryCollector`, contextvar helpers, batched writer task
- `src/telemetry/pricing.py` — `PricingTable` loader + cost calculation
- `src/telemetry/query.py` — aggregate query functions (run summary, timeline, tree build, cost rollup, trends)
- `src/telemetry/api.py` — FastAPI router mounted under `/api/runs/*/telemetry` and `/api/sessions/*/telemetry`
- `config/pricing.yaml` — default pricing for Anthropic / OpenAI / DeepSeek / Qwen models
- `scripts/init_db.sql` — `telemetry_events` table + GIN index on payload + B-tree indexes on `(run_id, ts)`, `(session_id, ts)`, `(event_type, ts)`

**Touched existing modules (emission hooks only, no structural changes):**
- `src/agent/loop.py` — one `collector.record_llm_call(...)` after each LLM call
- `src/hooks/runner.py` — emit `tool_call` + `hook_event` from PostToolUse path
- `src/engine/session_runner.py` — contextvar set/reset around turn execution + turn boundary events
- `src/agent/tools/spawn_agent.py` — spawn_id generation + event emission
- `src/engine/pipeline.py` — pipeline_event emission at node/run boundaries
- `src/project/config.py` — `TelemetryConfig` section
- `src/main.py` — mount telemetry router, start/stop collector in FastAPI lifespan

**Not touched (verified by design):**
- Agent core (`create_agent`, `AgentState`) — telemetry is fully external
- Tool interface — event emission stays in the hook path, not in tools themselves
- MessageBus / Gateway — already flows through SessionRunner, emissions at runner level are sufficient

**Dependencies:**
- No new Python packages (uses existing `sqlalchemy`, `pydantic`, `fastapi`)
- `contextvars` (stdlib) for turn-context propagation across async boundaries

**Backwards compatibility:**
- Telemetry is **off-by-default** via `TelemetryConfig.enabled = True` (enabled, but cheap to flip off for tests / local dev)
- Disabling telemetry means `collector.record_*()` becomes a no-op; zero additional latency on the hot path
- No existing REST endpoints change semantics
- No existing event stream (`streaming/events.py` StreamEvent) changes — telemetry is a separate, write-side system
