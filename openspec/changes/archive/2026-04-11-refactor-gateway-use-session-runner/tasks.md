## 1. Pre-flight

- [x] 1.1 Grep for any external callers of `Gateway._run_agent` — found 3 mock patches in `scripts/test_claw_gateway.py` (lines 55/145/194); no production callers. Will update in section 4.
- [x] 1.2 Grep for any external readers of `Gateway._session_locks` — none outside gateway.py itself. Safe to delete.
- [x] 1.3 Confirm `StreamEvent` terminal event name is `"done"` in `src/streaming/events.py:75` — confirmed, listed in `EVENT_TYPES` frozenset line 21.
- [x] 1.4 Confirm `runner.notify_new_message()` and `runner.add_subscriber()` / `runner.remove_subscriber()` signatures match `src/api/sessions.py` reference usage — confirmed: `add_subscriber() -> Queue[StreamEvent]`, `remove_subscriber(q)`, `notify_new_message()` at `session_runner.py:137/143/165`.

## 2. Gateway rewrite

- [x] 2.1 Added imports: `get_or_create_runner`, `append_message`, `get_messages`; `MessageBus` moved to TYPE_CHECKING per ruff TC001
- [x] 2.2 Module-level constant `_BUS_SUBSCRIBER_TIMEOUT_SECONDS = 300.0`
- [x] 2.3 `_process_message` rewritten: resolve → append user → get_or_create_runner → _wait_for_turn → refresh_session → publish_outbound
- [x] 2.4 `_wait_for_turn` wraps subscribe/notify/await loop in try/finally with `remove_subscriber`
- [x] 2.5 TimeoutError branch logs WARNING and returns None; caller skips publish
- [x] 2.6 `_run_agent` method deleted
- [x] 2.7 `_session_locks` field deleted; `_dispatch` now calls `_process_message` directly
- [x] 2.8 Helper `_read_latest_assistant_message` handles both str and list[dict] content shapes, falls back to `"(no response)"`
- [x] 2.9 Outer exception handler preserved — still publishes "Sorry, an error occurred..."
- [x] 2.10 `/resume` branch remains the first check in `_process_message`, bypasses runner entirely
- [x] 2.11 `ruff check src/bus/gateway.py` — all checks passed

## 3. Integration test (new)

**Note 2026-04-11**: cases D (timeout) and E (/resume bypass) are fully covered by the fully-mocked `scripts/test_claw_gateway.py` and do not need duplicating in the PG-backed file. Retained only cases A, B, C here.

- [x] 3.1 Created `scripts/test_bus_session_runner_integration.py` (matches pattern from `scripts/test_rest_api_integration.py`, graceful skip on DB unavailability)
- [x] 3.2 Setup uses `patch("src.agent.factory.create_agent", ...)` + `patch("src.engine.session_runner.agent_loop", ...)`; fake loop yields `text_delta` + `done` AND appends an assistant message to `state.messages` so runner persistence is exercised
- [x] 3.3 Test case A — asserts bus and REST see the same `SessionRunner` instance from registry, both user messages land in the same `Conversation.messages` in order
- [x] 3.4 Test case B — first bus message creates runner, assistant reply from text_delta is published as outbound
- [x] 3.5 Test case C — two concurrent `asyncio.gather(_process_message, _process_message)`; both outbounds published, both user msgs persisted, one runner in registry
- [x] 3.6 Cases D/E covered in `test_claw_gateway.py` (timeout via monkey-patched constant; /resume via mocked `_handle_resume`)
- [x] 3.7 Execute `python scripts/test_bus_session_runner_integration.py` — 17 passed, 0 failed

## 4. Regression test update (`test_claw_gateway.py`)

**Correction 2026-04-11**: the original tasks pointed at `test_streaming_regression.py` 9.x, but that file has no gateway tests (9.1 = spawn_agent, 9.2 = pipeline). The real gateway regression tests live in `scripts/test_claw_gateway.py` — it patches `_run_agent` in 3 places (lines 55, 145, 194). Retargeting here.

- [x] 4.1 Read `scripts/test_claw_gateway.py` end-to-end — catalogued 5 test functions; 3 patched `_run_agent`
- [x] 4.2 Rewrote `test_e2e` to patch `get_or_create_runner` with a fake runner (pre-loaded `done` event in add_subscriber queue) + `get_messages` returning a seeded assistant message
- [x] 4.3 `test_error_handling` kept — `resolve_session` RuntimeError path still works unchanged
- [x] 4.4 `test_serial_per_session` removed (obsolete; serialization is now the runner's job); replaced with `test_subscriber_timeout` and `test_resume_bypass` + `test_structured_content`
- [x] 4.5 `test_cross_session` kept — patches `_process_message` directly
- [x] 4.6 `test_stop` kept — unchanged, tests `_active_tasks` cleanup
- [x] 4.7 `python scripts/test_claw_gateway.py` — 23 passed, 0 failed

## 5. Cross-check existing session-runner tests still pass

- [x] 5.1 Run session_runner (11/11) + session_registry (20/20) — all pass
- [x] 5.2 Run REST integration (40/40, 1 skip) + sse_backfill (16/16) + auth (14/14) — all pass

## 6. Validation and archive prep

- [x] 6.1 Run `openspec validate refactor-gateway-use-session-runner --strict` — passed
- [x] 6.2 Full fast test suite: session_runner 11 + session_registry 20 + bus_integration 17 + streaming_regression 11 — all pass
- [x] 6.3 Update `.plan/progress.md`: mark carry-over done, remove the 🟥 START HERE block, set next step = Phase 6.2
- [x] 6.4 Remove memory entry `next_task_gateway_session_runner.md` and its line in `MEMORY.md`
- [ ] 6.5 `git add` the gateway + tests + openspec change dir; commit with message referencing the change name
- [ ] 6.6 Run `/openspec-archive-change refactor-gateway-use-session-runner`
