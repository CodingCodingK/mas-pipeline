## 1. Schema and config

- [x] 1.1 Add `telemetry_events` table + indexes to `scripts/init_db.sql` (columns per telemetry-collection spec; GIN on payload; B-tree on `(run_id,ts)`, `(session_id,ts)`, `(event_type,ts)`, `(project_id,ts)`)
- [x] 1.2 Add `TelemetryConfig` pydantic model to `src/project/config.py` with all six fields defaulted; wire into top-level `Settings` under `telemetry:` key
- [x] 1.3 Create `config/pricing.yaml` with default prices for Anthropic (claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5), OpenAI (gpt-4o, gpt-4o-mini), DeepSeek (deepseek-chat, deepseek-reasoner), Qwen (qwen-max, qwen-plus); each with `input_usd_per_1k_tokens`, `output_usd_per_1k_tokens`, `cache_read_discount_factor`

## 2. Telemetry module core

- [x] 2.1 Create `src/telemetry/__init__.py` exporting `TelemetryCollector`, `NullTelemetryCollector`, `get_collector`, the three contextvars
- [x] 2.2 Create `src/telemetry/events.py` — 8 pydantic/dataclass event types (`LLMCallEvent`, `ToolCallEvent`, `AgentTurnEvent`, `AgentSpawnEvent`, `PipelineEvent`, `SessionEvent`, `HookEvent`, `ErrorEvent`) + `TelemetryEvent` union type with `event_type` discriminator
- [x] 2.3 Create `src/telemetry/pricing.py` — `PricingTable` dataclass, `load_pricing(path) -> PricingTable`, `calculate_cost(usage, provider, model) -> float | None` implementing the formula from the spec; log WARNING once per unseen `(provider,model)` pair; document the yaml schema as a top-of-file comment so future maintainers can edit without reading source
- [x] 2.4 Create `src/telemetry/collector.py`:
  - Define `current_turn_id`, `current_spawn_id`, `current_run_id` contextvars at module level
  - Implement `TelemetryCollector` with `__init__(config, db_session_factory)`, the eight `record_*` methods, bounded `asyncio.Queue`, `_writer_loop` task, `start()`, `stop()` with 10s drain timeout
  - Implement `reload_pricing()` — re-reads `pricing_table_path` and atomically swaps `self._pricing` to the new table; logs count of models loaded
  - Implement `NullTelemetryCollector` subclass with all `record_*` as no-ops
  - `record_*` methods: `if not self._enabled: return` first, then build event, then `queue.put_nowait(event)` with QueueFull handling (drop-oldest + rate-limited WARNING)
  - `_writer_loop`: drain every `flush_interval_sec` OR when size >= `batch_size`; bulk INSERT via SQLAlchemy core
- [x] 2.5 Write `scripts/test_telemetry_collector.py`:
  - Queue append + bulk flush at batch size
  - Flush at interval
  - Drop-oldest when full + WARNING rate-limiting
  - Graceful shutdown drain
  - Disabled collector zero-queue path
  - Null collector interchangeable
  - Pricing table: known model, unknown model, cache-read discount
- [x] 2.6 Write `scripts/test_telemetry_contextvars.py`:
  - `current_turn_id` set/reset via context manager
  - Concurrent task contexts isolated
  - `asyncio.create_task` inherits snapshot
  - Reset via token restores prior value

## 3. Emission wiring

- [x] 3.1 `src/agent/loop.py` — inject collector via module-level `get_collector()`; after each `call_llm` response (success path) call `collector.record_llm_call(provider, model, usage, latency_ms, finish_reason)`; on exception path call `record_llm_call` with `finish_reason='error'` + `record_error('llm', exc)` then re-raise
- [x] 3.2 `src/hooks/runner.py` — in PostToolUse dispatch: after tool completes, call `collector.record_tool_call(tool_name, args_preview, duration_ms, success, error)`; after every hook returns, call `collector.record_hook_event(hook_type, decision, latency_ms, rule_matched)`
- [x] 3.3 `src/engine/session_runner.py` — wrap the turn-body in `collector.turn_context(agent_role, input_preview)` async context manager (new helper on collector) that sets `current_turn_id`, captures `started_at`/`input_preview`, and on exit captures `ended_at`/`output_preview` and emits the `agent_turn` event; add `record_session_event` calls at `__init__` (`created`), first message (`first_message`), and all exit paths (`idle_exit`/`max_age_exit`/`shutdown_exit`)
- [x] 3.4 `src/tools/builtins/spawn_agent.py` — generate `spawn_id`; call `collector.record_agent_spawn(parent_role, child_role, task_preview, spawn_id)`; `current_spawn_id.set(spawn_id)` immediately before `asyncio.create_task` for the child so the task context inherits it; child's first `agent_turn` automatically picks it up in its own `turn_context`
- [x] 3.5 `src/engine/pipeline.py` — at pipeline start, set `current_run_id` contextvar and emit `pipeline_start`; at each node boundary emit `node_start`/`node_end`/`node_failed`; at pause/resume/end emit corresponding events; reset `current_run_id` on `pipeline_end`
- [x] 3.6 `src/bus/gateway.py` — in the outer exception handler of `_process_message`, call `collector.record_error(source='gateway', error_type=type(exc).__name__, message=str(exc)[:500], context={'session_id': ..., 'inbound_topic': ...})` before publishing the error response so the coarse reason (exception class + first line) lands in the `error` event payload
- [x] 3.7 `src/main.py` — construct `TelemetryCollector` in FastAPI lifespan startup (or `NullTelemetryCollector` if `telemetry.enabled=False`), store on `app.state.telemetry_collector`, wire `get_collector` to read from it; call `collector.start()` in lifespan startup, `collector.stop()` in lifespan shutdown

## 4. Query layer and REST API

- [x] 4.1 Create `src/telemetry/query.py`:
  - `get_run_summary(run_id) -> dict` — total tokens/cost/duration/event_counts
  - `get_run_timeline(run_id) -> list[event]` — flat sorted by ts
  - `get_run_tree(run_id) -> dict` — hierarchical tree (A6 algorithm from design.md Decision 3)
  - `get_run_agents(run_id) -> list[dict]` — per-agent rollup
  - `get_run_errors(run_id) -> list[event]`
  - `get_session_summary(session_id)`, `get_session_tree(session_id)` — same shapes, session-scoped
  - `get_project_cost(project_id, from_, to_, group_by, pipeline) -> list[dict]`
  - `get_project_trends(project_id, from_, to_) -> dict` — latency/tokens over time
- [x] 4.2 Create `src/telemetry/api.py` — FastAPI router with all 10 endpoints from the spec (9 query + `POST /api/admin/telemetry/reload-pricing`); 404 on missing resource; reuses existing API key auth dependency; reload endpoint calls `collector.reload_pricing()` and returns `{"models_loaded": N}`
- [x] 4.3 `src/main.py` — mount telemetry router under `/api/`
- [x] 4.4 Write `scripts/test_telemetry_query.py`:
  - Seed a fake run with known events via direct collector calls; assert summary aggregates match
  - Tree reconstruction with coordinator + 2 spawned children; assert hierarchy is correct
  - Cost rollup by day with fixed events; assert grouping is correct
  - Trends across 2 runs; assert latency averages
- [x] 4.5 Write `scripts/test_telemetry_api.py`:
  - All 10 endpoints return 200 with expected shape on seeded data
  - 404 on nonexistent run/session/project
  - Auth: missing API key → 401 on all endpoints
  - Cost endpoint filter params all work (`?from=...&to=...&group_by=day&pipeline=blog_generation`)
  - Reload-pricing: edit a temp yaml, POST, assert new model appears in a subsequent cost calculation; assert existing persisted events are untouched

## 5. Integration tests (real PG/Redis)

- [x] 5.1 Write `scripts/test_telemetry_integration.py` (same graceful-skip pattern as existing integration tests):
  - Run a fake pipeline end-to-end through `pipeline.py` with mocked agent; assert `pipeline_event` + `llm_call` + `tool_call` + `agent_turn` all land in `telemetry_events` with correct linking
  - Run a chat session through `SessionRunner` with mocked `agent_loop`; assert same for session-scoped events
  - Trigger a coordinator-spawns-researcher scenario; assert `agent_spawn` + child `agent_turn` has `spawned_by_spawn_id` linking back
  - Pipeline failure path: node raises → assert `node_failed` + `pipeline_end` + `error` events all present
  - Disabled path: set `enabled=False`, run same scenarios; assert zero rows in `telemetry_events`
- [x] 5.2 Write `scripts/test_telemetry_rest_integration.py`:
  - Seed via API-triggered pipeline run; then `GET /api/runs/{id}/telemetry/tree`; assert tree structure matches
  - `GET /api/projects/{id}/telemetry/cost?group_by=day` on a day with 2 runs; assert aggregated total

## 6. Regression tests

- [x] 6.1 Run `scripts/test_session_runner.py` and `scripts/test_session_registry.py` — must still pass (new contextvar setup is additive; turn lifecycle unchanged)
- [x] 6.2 Run `scripts/test_streaming_regression.py` — `agent_loop` + `pipeline.py` emission must not disturb `spawn_agent` or pipeline end-to-end behavior
- [x] 6.3 Run `scripts/test_claw_gateway.py` and `scripts/test_bus_session_runner_integration.py` — gateway telemetry emission in the error path must not change externally-observable behavior
- [x] 6.4 Run `scripts/test_rest_api_integration.py`, `scripts/test_rest_api_auth.py`, `scripts/test_rest_api_sse_backfill.py` — telemetry router mounting must not affect existing routes

## 7. Validation and archive prep

- [x] 7.1 Run `openspec validate add-telemetry-collection --strict`
- [x] 7.2 Run the full telemetry test surface: `test_telemetry_collector.py`, `test_telemetry_contextvars.py`, `test_telemetry_query.py`, `test_telemetry_api.py`, `test_telemetry_integration.py`, `test_telemetry_rest_integration.py`
- [x] 7.3 Run regression suite (task 6.1–6.4)
- [x] 7.4 Update `.plan/progress.md`: mark Phase 6.2 done, set next step = Phase 6.3 (Notify)
- [x] 7.5 `git add` all new files + modified files + openspec change dir; commit
- [x] 7.6 Run `/openspec-archive-change add-telemetry-collection`
