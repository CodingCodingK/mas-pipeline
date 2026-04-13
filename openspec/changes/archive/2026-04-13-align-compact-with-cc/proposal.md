## Why

Six bugs surfaced in the compact / resume / token-budget path during Phase 8 smoke testing. Root-causing them revealed that our compact subsystem had drifted from Claude Code's proven design in several places — we invented a separate `compact_summaries` table, used a cheap "light" tier for summarization, truncated resume history to 200 messages, and bolted on over-engineered token heuristics. Aligning with CC's actual approach collapses 6 fixes into one coherent redesign and eliminates two whole concepts (separate table + light-tier summarizer) rather than patching them.

## What Changes

- **BREAKING (internal)**: compact summary is now persisted inline in `conversations.messages` as a normal message entry with `metadata.is_compact_summary=true`, plus a separate boundary marker entry with `metadata.is_compact_boundary=true`. Append-only semantics — compact no longer shrinks the persisted history.
- `build_messages` / prompt assembly scans the message list from the tail for the most recent `compact_boundary` entry and only feeds messages *after* it to the model. Messages before the boundary remain in PG for audit / replay but are invisible to the LLM. Conversations without a boundary marker degrade to full history (backward compatible).
- `auto_compact` and `reactive_compact` now call the **main agent's adapter** (not `route("light")`). On prompt-too-long errors they drop the oldest batch and retry, capped at 2 attempts, matching CC's `truncateHeadForPTLRetry`.
- `SessionRunner` gains a `consecutive_compact_failures` counter; after 3 consecutive failures autocompact is skipped for the remainder of the session (circuit breaker, matches CC's `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES`). No user-visible error event is emitted.
- `get_session_history` loses its `max_messages=200` truncation parameter. Full history is loaded on resume.
- **REMOVED**: `compact_summaries` table, `CompactSummary` ORM model, `_save_summary` helper, and the DDL in `scripts/init_db.sql`. CC has no equivalent table — the summary lives inline.
- **WONTFIX**: `estimate_tokens` keeps the `len // 4` formula. CC uses the same formula; the proposed CJK-aware variant was over-engineering relative to upstream.
- New end-to-end test `scripts/test_compact_resume.py` exercises: compact → persist → resume → re-compact; boundary marker slicing; overflow-retry path; failure counter circuit breaker.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `compact`: requirements rewritten — summary persistence model, boundary marker semantics, same-adapter summarization, overflow-retry, circuit breaker, removal of separate summaries table.
- `context-builder`: `build_messages` adds compact-boundary slicing behavior.
- `session-manager`: `get_session_history` loads full history, `max_messages` parameter removed.
- `session-runner`: consecutive-compact-failure counter and circuit breaker behavior.

## Impact

- **Code**: `src/agent/compact.py`, `src/agent/loop.py`, `src/agent/context.py`, `src/bus/session.py`, `src/engine/session_runner.py`, `src/models.py`, `scripts/init_db.sql`.
- **Database**: drop `compact_summaries` table. `conversations.messages` JSONB gains two new metadata flag shapes (`is_compact_summary`, `is_compact_boundary`) — no schema migration needed, JSONB is schemaless.
- **Tests**: new `scripts/test_compact_resume.py`; existing `scripts/test_compact.py` updated for the new persistence shape and removal of `CompactSummary`.
- **Backward compatibility**: old sessions without boundary markers continue to work — `build_messages` degrades to full history when no boundary is found. Old sessions with `compact_summaries` rows are orphaned (table gone); no migration because the data was never consumed by any product path.
- **External API**: no REST changes, no adapter changes, no front-end changes.
