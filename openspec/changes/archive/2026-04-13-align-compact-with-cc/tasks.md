## 1. Remove CompactSummary table and model

- [x] 1.1 Delete `CompactSummary` class from `src/models.py`
- [x] 1.2 Delete `compact_summaries` CREATE TABLE statement from `scripts/init_db.sql`
- [x] 1.3 Add `DROP TABLE IF EXISTS compact_summaries CASCADE;` to `scripts/init_db.sql` before the CREATE section (idempotent for re-runs on old dev DBs)
- [x] 1.4 Delete `_save_summary` helper and `save_compact_summary` / any `CompactSummary` imports from `src/agent/compact.py`
- [x] 1.5 Grep the tree for `CompactSummary` / `compact_summaries` / `_save_summary` — confirm zero remaining references (test files included)

## 2. Rewrite compact to be append-only with boundary marker

- [x] 2.1 In `src/agent/compact.py`, change `auto_compact(messages, adapter, model)` signature: remove any internal `route("light")` call, take the adapter + model from caller
- [x] 2.2 Implement split-point computation: find the newest N messages whose token estimate fits within `30% * context_window`; the rest is the "older blob"
- [x] 2.3 Build the summary prompt (reuse existing prompt text — only the adapter and the persistence path change)
- [x] 2.4 Wrap the summarizer `adapter.call()` in try/except catching `LLMError`. On prompt-too-long / context-exceeded match (by error code OR message substring "context" / "too long" / "exceed"), drop oldest 50% of the older blob and retry once; on second failure re-raise
- [x] 2.5 Build the two new tail entries: `{"role": "user", "content": summary, "metadata": {"is_compact_summary": true}}` and `{"role": "system", "content": "", "metadata": {"is_compact_boundary": true, "turn": <turn>}}`
- [x] 2.6 Return `CompactResult(messages=original_list + [summary_entry, boundary_entry], summary=summary, tokens_before=..., tokens_after=<post-boundary slice estimate>)` — do NOT replace the input list
- [x] 2.7 Replicate the same logic for `reactive_compact` with 20% (not 30%) recent-fit ratio
- [x] 2.8 Update `CompactResult` field docstrings to reflect the new semantics (`tokens_after` is the post-boundary slice, not the whole list)

## 3. Wire compact at the loop level

- [x] 3.1 In `src/agent/loop.py`, find the current auto_compact / reactive_compact call sites
- [x] 3.2 Pass `state.adapter` and `state.model` to the compact call (drop any `route("light")` reference)
- [x] 3.3 Pass the current turn number to the compact call so the boundary marker can record it
- [x] 3.4 Wrap compact calls in a try/except that increments `state.consecutive_compact_failures` on exception, resets to 0 on success
- [x] 3.5 Guard the compact call with `if state.consecutive_compact_failures < 3` (circuit breaker). On first trip (exactly at 3), log INFO once. Do not emit error StreamEvent.
- [x] 3.6 Remove the old `TOKEN_LIMIT` exit branch that silently returned without any event (dead path once compact no longer replaces messages in place)
- [x] 3.7 Make sure `state.messages` is reassigned to `result.messages` (the appended list) after compact, so the runner sees the new tail entries

## 4. Update AgentState

- [x] 4.1 Add `consecutive_compact_failures: int = 0` field to `AgentState` in `src/agent/state.py` (or wherever it lives)
- [x] 4.2 Add `compact_breaker_tripped: bool = False` field (set once when the counter first reaches 3, prevents re-logging)

## 5. Update build_messages to slice at boundary

- [x] 5.1 In `src/agent/context.py::build_messages`, before emitting the history portion, scan `history` from tail to head for the most recent entry with `metadata.is_compact_boundary == True`
- [x] 5.2 If found: locate the immediately-preceding `is_compact_summary` entry; emit it as a plain `{"role": "user", "content": summary}` (strip metadata); then emit all messages AFTER the boundary
- [x] 5.3 If no boundary found: emit full history unchanged (backward compat)
- [x] 5.4 Add a metadata-stripper helper so ANY message with a `metadata` key has it removed before being returned (adapters should never see metadata)
- [x] 5.5 Confirm `parse_role_file` / identity / memory / skill layers are untouched

## 6. Session history full-load

- [x] 6.1 In `src/bus/session.py::get_session_history`, remove the `max_messages` parameter entirely
- [x] 6.2 Drop the `LIMIT` / slice in the implementation — load the full JSONB array
- [x] 6.3 Keep the existing `clean_orphan_messages` call at the end
- [x] 6.4 Update `src/engine/session_runner.py::_load_history_from_pg` (or whichever call site) to drop the `max_messages=200` kwarg
- [x] 6.5 Grep for any other `get_session_history(` call sites — update all of them

## 7. SessionRunner persistence path

- [x] 7.1 Verify `_persist_new_messages` does not need any change — confirm the length-diff logic works because compact now only appends
- [x] 7.2 Confirm `_pg_synced_count` is only ever incremented, never reset, after this change
- [x] 7.3 Delete any `on_compact` event-listener hook that assumed the message list would shrink (if one exists)

## 8. Tests

- [x] 8.1 Update existing `scripts/test_compact.py`: remove CompactSummary assertions, update auto_compact / reactive_compact expectations to the append-only shape
- [x] 8.2 Write new `scripts/test_compact_resume.py`:
  - [x] 8.2.1 Seed a conversation with ~60 messages, trigger auto_compact, assert messages length == 62 (original + summary + boundary) and the last two entries carry the correct metadata flags
  - [x] 8.2.2 Feed the post-compact list into `build_messages` and assert the pre-compact 60 are NOT in the emitted slice, the summary IS, and the boundary marker is NOT
  - [x] 8.2.3 Simulate PG resume: write the appended list to conversations.messages, call `get_session_history`, then `build_messages` — confirm the downstream adapter input is the same as before resume
  - [x] 8.2.4 Simulate two cascading compacts on one runner; assert only the newest boundary's summary is emitted, older summary+boundary are elided (covered in test_compact.py cascading test)
  - [x] 8.2.5 Mock adapter that raises prompt-too-long on first call, succeeds on retry — assert CompactResult is returned successfully (in test_compact.py)
  - [x] 8.2.6 Mock adapter that raises prompt-too-long on both calls — assert auto_compact re-raises (in test_compact.py)
  - [x] 8.2.7 Trip the circuit breaker: force three consecutive compact failures in loop, assert fourth attempt is skipped with no error StreamEvent and one INFO log
- [x] 8.3 Write `scripts/test_session_history_full_load.py`: seed a 1500-message conversation, call `get_session_history`, assert length == 1500
- [x] 8.4 Run the full existing test suite; fix any regression in `scripts/test_session_runner.py` / `test_rest_api_integration.py` / `test_bus_session_runner_integration.py` caused by the get_session_history signature change (updated test_loop_compact.py section 3 for removed blocking-limit branch; the one remaining failure in test_bus_session_runner_integration.py is pre-existing and unrelated)

## 9. Smoke test and validate

- [ ] 9.1 Bring up the docker stack: `docker compose down -v && docker compose up -d` (deferred to manual validation)
- [ ] 9.2 Run `scripts/smoke_test.sh` and confirm all endpoints still pass (deferred to manual validation)
- [ ] 9.3 Manually drive a chat session through > 100 messages to force a real compact; inspect `conversations.messages` JSONB in PG to confirm the summary + boundary entries landed (deferred to manual validation)
- [x] 9.4 Run `openspec validate align-compact-with-cc --strict` — must pass
- [ ] 9.5 Run `openspec-sync-specs` agent / `openspec archive align-compact-with-cc` path after user review

## 10. Progress and memory

- [x] 10.1 Update `.plan/progress.md` with a "Phase 8.5 (or post-8 hotfix) done" entry summarizing what shipped
- [x] 10.2 If any surprising insight surfaced during implementation worth keeping in memory, save it per the auto-memory rules
