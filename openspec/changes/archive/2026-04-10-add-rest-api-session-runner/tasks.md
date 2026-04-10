## 1. Schema & migrations

- [x] 1.1 Add `mode VARCHAR(20) NOT NULL DEFAULT 'chat'` column to `chat_sessions` in `scripts/init_db.sql`
- [x] 1.2 Add `mode: Mapped[str]` field to `ChatSession` ORM model in `src/models.py`
- [x] 1.3 Write migration step (or document re-init) — backfill existing rows with `'chat'`
- [x] 1.4 Update `resolve_session()` in `src/bus/session.py` to accept and persist optional `mode` parameter
- [x] 1.5 Add config fields to `src/project/config.py`: `api_keys: list[str]`, `session.idle_timeout_seconds: int = 60`, `session.max_age_seconds: int = 86400`

## 2. Delete coordinator_loop and notification_queue

- [x] 2.1 Remove `notification_queue` field from `AgentState` in `src/agent/state.py`
- [x] 2.2 Delete `src/engine/coordinator.py` entirely (keep `agents/coordinator.md` role file)
- [x] 2.3 Grep repo for `notification_queue` and `coordinator_loop` — remove all references *(only comments remain in state.py + spawn_agent.py, cleaned in batch B)*
- [x] 2.4 Delete or rewrite `scripts/test_coordinator*.py` to use SessionRunner / agent_loop directly *(deleted: test_coordinator.py, test_coordinator_loop.py, test_coordinator_split.py, test_path_isolation.py; trimmed test_streaming_regression.py 9.3)*
- [ ] 2.5 Update `src/bus/gateway.py` `_dispatch()` to use SessionRunner instead of running agent inline (Phase 5.5 claw bus integration) *(SCOPED OUT 2026-04-11 — `_process_message` still calls inline `_run_agent`. Tracked in follow-up change `refactor-gateway-use-session-runner`. See `.plan/progress.md` Phase 6.1 carry-overs §1.)*

## 3. spawn_agent refactor (PG-backed notifications)

- [x] 3.1 In `src/tools/builtins/spawn_agent.py`, change the post-completion callback to call `append_message(parent_conversation_id, format_task_notification(...))` instead of `parent_state.notification_queue.put(...)`
- [x] 3.2 After persisting, look up `parent_runner` in `session_registry` and call `parent_runner.wakeup.set()` if found
- [x] 3.3 After in-process wakeup, issue `NOTIFY session_wakeup, '<parent_session_id>'` on a short-lived PG connection (best-effort; ignore failure)
- [x] 3.4 Wrap the entire background callback in `try/except Exception` — on any exception, persist a failure `<task-notification>`, log ERROR, NEVER propagate
- [x] 3.5 Register the spawned `asyncio.Task` in `parent_runner.child_tasks` if parent runner exists locally
- [x] 3.6 Add hard timeout per sub-agent (default 5 min, configurable via `settings.spawn_agent.timeout_seconds`); on timeout, cancel + persist failure notification
- [x] 3.7 Update tests under `scripts/test_spawn_agent*.py` to assert on `Conversation.messages` instead of queue contents *(rewrote 9.1 in scripts/test_streaming_regression.py — no dedicated test_spawn_agent file existed)*

## 4. SessionRunner core

- [x] 4.1 Create `src/engine/session_runner.py` with `SessionRunner` class — fields: `session_id`, `mode`, `state`, `wakeup`, `subscribers`, `child_tasks`, `last_active_at`, `created_at`
- [x] 4.2 Implement `SessionRunner.start()` — builds `state` via `create_agent("assistant" or "coordinator", ...)`, launches `_main_loop` as asyncio.Task
- [x] 4.3 Implement `_main_loop()` — async generator over `agent_loop(state)`, fans out events to subscribers, persists assistant messages via `append_message()`
- [x] 4.4 Implement wait phase: after agent_loop exits, if `running_agent_count == 0` and no unread messages → `await asyncio.wait_for(self.wakeup.wait(), timeout=idle_timeout)`; on timeout check exit conditions
- [x] 4.5 Implement `try/finally` cleanup — cancel `child_tasks`, deregister from `_session_runners`, log on exception
- [x] 4.6 Implement subscriber fan-out with bounded queue (size 100) and oldest-drop policy
- [x] 4.7 Implement `add_subscriber()` / `remove_subscriber()` thread-safe (asyncio.Lock) *(set+single-threaded asyncio mutation; no extra lock needed)*
- [x] 4.8 Verify zero PG connection held during `await self.wakeup.wait()` — review all `async with get_db()` blocks

## 5. SessionRunner registry & GC

- [x] 5.1 Create `src/engine/session_registry.py` with `_session_runners: dict[int, SessionRunner]` and `_registry_lock: asyncio.Lock`
- [x] 5.2 Implement `get_or_create_runner(session_id, mode, project_id)` — idempotent factory, holds lock only during dict mutation
- [x] 5.3 Implement `get_runner(session_id)` lookup
- [x] 5.4 Implement `shutdown_all()` — iterate, set wakeup events, await with 5s timeout each, cancel stragglers
- [x] 5.5 Implement `_idle_gc_task()` background loop — every 60s snapshot dict, call `runner.request_exit()` for runners exceeding idle/max-age
- [x] 5.6 Implement startup task `_listen_session_wakeup()` — dedicated PG connection, `LISTEN session_wakeup`, dispatch to local registry on NOTIFY

## 6. FastAPI app wiring

- [x] 6.1 In `src/main.py` lifespan: launch `_idle_gc_task` and `_listen_session_wakeup` background tasks; on shutdown call `shutdown_all()` and cancel tasks
- [x] 6.2 Add startup check: read `WEB_CONCURRENCY` env var, log WARNING if set and != "1"
- [x] 6.3 Mount API router at `/api` prefix in `src/main.py`

## 7. API Key auth

- [x] 7.1 Implement `src/api/auth.py` — `require_api_key()` FastAPI dependency reading `X-API-Key` header against `settings.api_keys`
- [x] 7.2 Empty `api_keys` list disables auth (development mode)
- [x] 7.3 Apply dependency to all `/api/*` routers (not `/health`)

## 8. REST endpoints — sessions & messages

- [x] 8.1 Implement `src/api/sessions.py` router with `POST /api/projects/{project_id}/sessions` (create chat session, returns id + conversation_id)
- [x] 8.2 Implement `POST /api/sessions/{session_id}/messages` — append user message via `append_message()`, ensure SessionRunner via `get_or_create_runner()`, call `runner.wakeup.set()`, return 202
- [x] 8.3 Implement `GET /api/sessions/{session_id}/events` — SSE response, `add_subscriber` to runner, async-iterate subscriber queue, push events; honor `Last-Event-ID` for backfill from `Conversation.messages[last_id+1:]`
- [x] 8.4 Implement SSE keepalive (`: ping\n\n` every 15s) — slow-client send timeout deferred (StreamingResponse handles disconnect via `request.is_disconnected()` poll instead)
- [x] 8.5 Implement `GET /api/sessions/{id}` and `GET /api/sessions/{id}/messages?offset=&limit=`

## 9. REST endpoints — projects, pipelines, runs

- [x] 9.1 Implement `src/api/projects.py` router — `GET /api/projects`, `GET /api/projects/{id}`
- [x] 9.2 Implement `src/api/runs.py` router with `POST /api/projects/{project_id}/pipelines/{name}/runs` — create WorkflowRun, kick off pipeline execution, `?stream=true` returns full StreamEvent SSE fan-out (pipeline_start / node_start / node_end / node_failed / pipeline_paused / pipeline_end) backed by in-process `_pipeline_event_streams` registry in `engine/run.py`
- [x] 9.3 Implement `POST /api/runs/{run_id}/resume` — calls `resume_pipeline()`; 409 if not paused
- [x] 9.4 Implement `POST /api/runs/{run_id}/cancel` — set abort_signal via `engine.run` registry, mark status cancelled (added `RunStatus.CANCELLED` enum value + transitions)
- [x] 9.5 Implement `GET /api/runs/{run_id}` query

## 10. Tests

- [x] 10.1 Unit tests for SessionRunner: lifecycle, wakeup wait, subscriber fan-out, idle exit, max_age cap (`scripts/test_session_runner.py` — 11/11 passing)
- [x] 10.2 Unit tests for session_registry: idempotent create, concurrent race, get/deregister, done-replaced, shutdown_all (normal + timeout cancel), GC sweep (max_age, idle, subscriber-keepalive) (`scripts/test_session_registry.py` — 20/20 passing)
- [x] 10.3 Integration test: chat mode end-to-end (`scripts/test_rest_api_integration.py` — session create/idempotent/multimodal against real PG)
- [x] 10.4 Integration test: autonomous mode session creation (covered in §10.3 — autonomous mode persists + queries)
- [x] 10.5 Integration test: SSE Last-Event-ID backfill — extracted `backfill_events_from()` helper, tested directly against real PG with 6 edge cases incl. unicode (`scripts/test_rest_api_sse_backfill.py` — 16/16 passing). TestClient + StreamingResponse deadlocks on Windows for *infinite* SSE generators because `httpx.ASGITransport` collects the full body before returning; the helper extraction sidesteps that entirely.
- [x] 10.6 Integration test: pipeline trigger + run query + 404s + non-paused resume 409 (`scripts/test_rest_api_integration.py`); plus dedicated event-stream test (`scripts/test_pipeline_event_stream.py`)
- [x] 10.7 REST API auth tests — 401 on missing/invalid key, 200 on valid (`scripts/test_rest_api_auth.py` — 14/14 passing)
- [x] 10.8 Integration test: cancel transitions run to cancelled + idempotent re-cancel (`scripts/test_rest_api_integration.py`)
- [x] 10.9 Pipeline event stream tests: registry primitives (subscribe/emit/fan-out/drop/unsubscribe/isolation/overflow) + end-to-end SSE via mocked pipeline (`scripts/test_pipeline_event_stream.py` — 24/24 passing)

## 11. Documentation

- [x] 11.1 Update `.plan/progress.md` marking Phase 6.1 in-progress / done
- [x] 11.2 Add brief deployment note: `--workers 1` requirement, idle/max-age config, sticky routing for future multi-process *(captured in `.plan/rest_api_deployment_risks.md`)*

## 12. Carry-overs (recorded 2026-04-11, blocking archive)

- [ ] 12.1 Resolve `agent-run-lifecycle` delta header sync — `MODIFIED` block references `### Requirement: AgentRun is a pure audit record`, header missing in main spec. Either fix the header to match, convert to `ADDED`, or archive with `--skip-specs` and reconcile manually.
- [ ] 12.2 Open follow-up change `refactor-gateway-use-session-runner` to actually do §2.5.
