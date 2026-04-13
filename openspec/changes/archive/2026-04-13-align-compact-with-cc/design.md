## Context

Phase 8 smoke testing surfaced six bugs in the compact / resume / persistence path:

| # | Symptom | Root cause |
|---|---|---|
| A | Assistant replies lost from PG after compact | `auto_compact` replaces `state.messages` in place (e.g. 201 → 22), but `SessionRunner._pg_synced_count` stays at 200. Subsequent `_persist_new_messages` length comparisons are off by ~180. |
| B | `compact_summaries.session_id` is empty string and column type is `String(255)` | `_save_summary` hardcodes `""`; ORM column is `str` when it should reference `chat_sessions.id` (int). |
| C | Light-tier summarizer overflows its own context window | `auto_compact` calls `route("light")`; when the older-messages blob itself exceeds the light tier's window (e.g. deepseek-chat 65K), the summary call crashes. |
| D | Resume with > 200-message history silently loses early turns | `get_session_history(max_messages=200)` hard-truncates load-from-PG. Compact can't reach the dropped messages. |
| E | Over 95% blocking limit hangs silently | `auto_compact` failure / blocking-limit path sets `exit_reason = TOKEN_LIMIT` and returns without a user-visible signal. |
| F | Chinese-heavy conversations misestimate tokens by ~3x | `estimate_tokens` uses `len / 4`, which over-counts ASCII and under-counts CJK. |

Cross-referencing Claude Code's source (`D:\github\hello-agents\claude-code\src`) revealed that most of these divergences are self-inflicted — our design drifted from CC's proven approach in places where we had no justification for the divergence. Two of the bugs (E, F) turn out to be **non-problems** once aligned with CC.

## Goals / Non-Goals

**Goals:**
- Fix A/B/C/D with a single coherent redesign that mirrors CC's persistence + summarization model.
- Eliminate concepts CC doesn't have: the `compact_summaries` table, the light-tier summarizer, the 200-message resume cap.
- Keep the public surface (adapter, REST, front-end) untouched.
- Backward-compatible with existing sessions: old histories without boundary markers continue to work via a degrade-to-full-history path.

**Non-Goals:**
- Improving token estimation accuracy for CJK content (F): **wontfix** — CC accepts the same inaccuracy, and the proposed fix is over-engineering relative to upstream.
- Emitting user-visible "context exceeded" errors (E): **wontfix** — CC explicitly stays silent and uses a circuit breaker. We match.
- Introducing a dedicated compact model configuration: **wontfix** — CC uses the main loop model for summarization, and so do we now.
- Data migration for orphaned `compact_summaries` rows: the table's contents were never consumed by any product path; drop without migration.
- `microcompact` (tool-result scrubbing) behavior is unchanged — only `auto_compact` / `reactive_compact` are touched.

## Decisions

### D1 — Persistence model: append-only log with boundary marker

**Chosen**: compact writes two new messages to the tail of `conversations.messages`:
1. A summary entry: `{"role": "user", "content": "<summary>", "metadata": {"is_compact_summary": true}}`
2. A boundary marker: `{"role": "system", "content": "", "metadata": {"is_compact_boundary": true, "turn": N}}`

The pre-compact messages remain in PG untouched. Compact *grows* the log; it never shrinks it. `_pg_synced_count` just keeps incrementing monotonically — no drift possible.

At prompt-assembly time, `build_messages` scans the tail backward for the most recent `is_compact_boundary` marker and only feeds the model messages **after** the marker (plus any system prefix). Pre-boundary messages are audit-only.

**Alternatives considered**:
- `A1` (original proposal): keep summary in RAM, don't persist. *Rejected*: loses the audit trail CC provides and doesn't actually fix `_pg_synced_count` — the in-memory array still shrinks, still drifts.
- `A2`: persist summary as a plain user message with no flag. *Rejected*: downstream model would see "[CONVERSATION SUMMARY]" as real user input; also no way for `build_messages` to find the slice point reliably.
- Separate `compact_boundaries` sidecar table. *Rejected*: adds a query on every prompt build.

**Rationale**: matches CC exactly (`compact.ts:616-625` and the `getMessagesAfterCompactBoundary` path in `query.ts:365`). Append-only semantics preserve the "messages is an immutable log" invariant that both `_pg_synced_count` and `_sync_inbound_from_pg` rely on. Flag-based dispatch keeps old messages schema-compatible — a missing `metadata` field is treated as "no flag", which is correct default behavior for pre-existing data.

### D2 — Carrier: `metadata` dict flag, not new `role` values

**Chosen**: reuse standard roles (`user` / `system`) and add a `metadata` dict to the message entry with boolean flags.

**Alternatives considered**: new role values like `"compact_summary"` / `"compact_boundary"`. *Rejected* because adapter serializers, message validators, and every downstream tool that pattern-matches on `role` would need updating. CC also goes the flag route (`isCompactSummary`, `isVisibleInTranscriptOnly`).

**Rationale**: minimal blast radius. Only `build_messages` and the compact writer need to know about the flags. Adapters, orchestrator, persistence layer all see regular user/system messages. JSONB is schemaless so no migration is needed.

### D3 — Summarizer adapter: main agent, not light tier

**Chosen**: `auto_compact` / `reactive_compact` receive the same `adapter` + `model` that the main agent is running on. The `route("light")` call is removed.

On `prompt_too_long` errors from the summarizer call, catch → drop the oldest N messages from the summarization blob → retry. Capped at 2 retries; further failure counts against the circuit breaker.

**Alternatives considered**:
- `C1` (original proposal): map-reduce over older messages. *Rejected*: more complex than CC, and CC's experience shows head-drop is sufficient.
- `C3`: new `settings.compact_model`. *Rejected*: more config surface, no real benefit, and still crashes the same way on overflow.

**Rationale**: matches CC (`compact.ts:1294` uses `mainLoopModel`; `truncateHeadForPTLRetry` at `compact.ts:245-293`). Uses the agent's own context window so overflow is harder to hit in the first place. No new config to tune.

### D4 — Resume history load: no cap

**Chosen**: `get_session_history` drops the `max_messages` parameter entirely. Loads full `conversations.messages` JSONB in one query.

**Rationale**: matches CC (`loadFullLog` in `conversationRecovery.ts:459-600`). PG JSONB fetch is O(1) per row; even a 10K-message history is a few MB — negligible. The 200-cap was a premature optimization that made compact useless on long histories.

### D5 — Failure handling: silent circuit breaker

**Chosen**: `SessionRunner` gains a `consecutive_compact_failures: int` field. On compact exception, increment. On success, reset to 0. When `>= 3`, skip auto-compact entirely for the remaining lifetime of the runner (log at INFO level, no user-facing event).

**Rationale**: matches CC's `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3` at `autoCompact.ts:70`, with silent swallowing at `autoCompact.ts:334-350`. Emitting errors to the user was my original impulse, but CC's reasoning is sound: the user can't do anything useful about "compact failed" except start a new session, and surfacing it creates noise on every long conversation that hits transient 429s.

### D6 — Drop `compact_summaries` table entirely

**Chosen**: delete the table from `init_db.sql`, delete the `CompactSummary` ORM model, delete `_save_summary`. The summary lives only in `conversations.messages`. No migration.

**Rationale**: CC has no such table. The table was added speculatively during Phase 3 and was never consumed by any product path (no REST endpoint, no UI, no query function reads from it). Keeping it would be maintaining dead weight. Linus rule: eliminate special cases rather than patch them — deleting the table makes bug B a non-bug.

### D7 — Token estimation: no change

**Chosen**: leave `estimate_tokens` using `len(json.dumps(msg, ensure_ascii=False)) // 4`.

**Rationale**: CC uses `length / 4` (`tokenEstimation.ts:203-208`). Our formula matches. For CJK-heavy content both implementations under-estimate by a factor of ~3, but this is a **conservative** direction — we trigger compact *later* than we theoretically should, not earlier. Since reactive compact catches the true overflow anyway, the extra accuracy isn't load-bearing. Not worth new code.

## Risks / Trade-offs

- **Risk**: `conversations.messages` JSONB schema drift — old messages lack `metadata`, new ones have flags. → **Mitigation**: `build_messages` uses `msg.get("metadata", {}).get("is_compact_boundary")`, so missing metadata is correctly treated as "no flag". Existing sessions keep working unchanged.
- **Risk**: models that don't return `prompt_too_long` as a distinct error code break the overflow-retry path. → **Mitigation**: catch broader `LLMError` + inspect message text for "context" / "too long" / "exceed"; if no match, treat as unrelated failure and count against circuit breaker. Log both paths.
- **Risk**: full-history load on resume makes cold starts slower for very long sessions. → **Mitigation**: 10K JSONB messages is still a single-row fetch and well under 100ms. If this ever becomes a real bottleneck we can add a server-side slice query; not worth pre-optimizing.
- **Risk**: old `compact_summaries` rows are orphaned after drop. → **Mitigation**: the table was write-only (no query path), so orphaning is equivalent to a no-op. Drop statement in `init_db.sql` is sufficient for fresh installs; for existing dev DBs the table will linger harmlessly until the next `docker compose down -v`.
- **Trade-off**: by matching CC's silent-failure posture, we accept that users with a broken compact loop will see the session slow down rather than see an explicit error. This is intentional — CC's experience is that the explicit error is worse UX than the slowdown.

## Migration Plan

1. Land the code change with `compact_summaries` DROP TABLE statement added to `scripts/init_db.sql` (idempotent via `DROP TABLE IF EXISTS`).
2. For running dev environments: either run `docker compose down -v` (recommended) or manually `DROP TABLE compact_summaries;`. The system continues to boot either way.
3. No backward-compat shim for old sessions — `build_messages` degrades to full-history when no boundary marker is present, which is the correct behavior for pre-change conversations.
4. Rollback: revert the commit. Because compact summaries are now inline in `conversations.messages`, rolling back will leave those flags in the JSONB harmlessly (old code ignores `metadata` field), and old sessions will re-compact normally under the old code path.

## Open Questions

None. All four decisions were pre-agreed with the user before proposal.
