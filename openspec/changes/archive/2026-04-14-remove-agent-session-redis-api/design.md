## Context

The `agent_session:*` Redis Hash API was specified in the 2026-04-09 `session-memory-compact` change as a "hot store Agent messages in Redis LIST with TTL, archive to PG on agent completion" pattern. The implementation landed in `src/session/manager.py` and the PG table was created in `scripts/init_db.sql`. No caller was ever wired up: sub-agent spawn writes directly to `agent_runs.messages` JSONB (added in `add-subagent-data-parity`, archived 2026-04-14), and the main session path uses `conversations.messages` JSONB via `SessionRunner`. The 2026-04-14 Redis audit (`.plan/redis_audit_2026-04-14.md`) confirmed zero `hget` / `hgetall` / `rpush` / `lrange` / `archive_agent_session` reader references in `src/` outside the manager module that defines them.

Independently, the 2026-04-10 `align-compact-with-cc` refactor changed the message-history contract: compact now rewrites the front of the history into a summary + boundary marker, persisted inline in the same JSONB column. Any hot-store candidate for agent messages must support an O(1) middle-rewrite, which Redis LIST does not.

This change deletes the dead API, the dead PG table, the dead config field, and the dead spec requirements in one sweep.

## Goals / Non-Goals

**Goals**
- Remove `src/session/manager.py` Agent Session functions and their imports with zero runtime-behavior change.
- Remove `AgentSessionRecord` ORM, `agent_sessions` PG table, and `agent_ttl_hours` config field.
- Remove the corresponding requirements from `session-manager` spec so the spec matches the shipped code.
- Cut `scripts/test_session_manager.py` Agent Session test cases; keep Conversation and `clean_orphan_messages` coverage green.

**Non-Goals**
- Do not touch `conversations.messages`, `agent_runs.messages`, `chat_session:*`, `gateway:lock`, or any `SessionRunner` behavior.
- Do not propose a replacement hot cache. If one is ever needed, it will be a new change with a documented reader surface from day one.
- No data migration: the PG table is empty in production (verified by operator spot-check) and the Redis keys are orphans with no TTL—the one-time cleanup commands in the proposal are sufficient.

## Decisions

### D1 — Path A (delete) over Path B (keep PG table, delete Redis only)

**Context**: We could delete only the Redis write path and keep the `agent_sessions` PG table "in case a future change wants to archive agent runs there."

**Decision**: Delete both. The PG table has zero rows and zero writers; keeping it is cargo-culting. If a future change needs an agent-run archive, `agent_runs.messages` JSONB already provides one (the 2026-04-14 `add-subagent-data-parity` change added `agent_runs.messages`, `tool_use_count`, `total_tokens` specifically for this purpose).

**Alternatives considered**:
- *Keep the PG table, delete Redis helpers*: rejected — leaves an unused table in the schema that costs mental overhead on every future init_db edit and misleads anyone reading the schema about the intended archival flow.
- *Keep everything, add a TTL on the Redis LIST*: rejected — a self-expiring cache with no readers is still unused code.

### D2 — Drop the spec requirements outright, no anti-requirement

**Decision**: Follow the same pattern as `remove-workflow-run-redis-cache`: mark the three Agent Session requirement blocks as REMOVED with a Reason field, do not replace them with a "SHALL NOT cache agent messages in Redis" anti-requirement.

**Why**: OpenSpec archives are the durable rationale store. A future engineer who proposes re-adding a Redis cache for agent messages will see the archived change explaining why it was removed. Anti-requirements in the live spec bloat it without adding value.

### D3 — Fold the compact-incompatibility argument into the REMOVED Reason

**Decision**: The Reason field for "Agent Session Redis hot storage" explicitly cites the compact incompatibility ("Redis LIST requires O(N) LRANGE+LTRIM+RPUSH to rewrite the front of the list, which compact does every N turns; negates the only reason LIST was chosen; PG JSONB handles append and compact at the same cost tier"). This preserves the architectural reasoning for future proposers so the same mistake is not repeated.

### D4 — DROP TABLE IF EXISTS in init_db.sql

**Decision**: Add `DROP TABLE IF EXISTS agent_sessions CASCADE;` below the existing `DROP TABLE IF EXISTS compact_summaries CASCADE;` line (L158-160). This is the same pattern used when `compact_summaries` was removed during the compact alignment.

**Why**: Existing deployments that re-run `init_db.sql` will automatically drop the orphan table. New deployments never create it. Zero manual operator steps for 90% of cases; the only manual path is a long-running PG that skips init, for which the operator cleanup one-liner in the PR description suffices.

## Risks / Trade-offs

- **Risk**: Zero-reader claim is wrong and something in a corner breaks.
  - **Mitigation**: Pre-deletion task re-greps the entire repo (`src/`, `scripts/`, `tests/`, `web/`) for all 5 function names, `AgentSessionRecord`, `agent_session:`, and `agent_ttl_hours` and records the exact hits. If any non-manager.py / non-test_session_manager.py / non-OpenSpec hit appears, pause the change.
- **Risk**: Test script breakage.
  - **Mitigation**: Task list explicitly runs `python scripts/test_session_manager.py` after the deletions and requires it to exit green. The Conversation and `clean_orphan_messages` assertions must still pass.
- **Risk**: An in-flight PG migration in production still has the `agent_sessions` table and drops it while rows happen to be in flight.
  - **Assessment**: Impossible — there are no writers in `src/`, so there are no rows in flight. Verified by a live `SELECT COUNT(*) FROM agent_sessions;` during task 1.

## Migration Plan

1. Pre-deletion verification (grep + live row count).
2. Code deletion in `src/session/manager.py`, `src/models.py`, `src/project/config.py`, `config/settings.yaml`, `scripts/init_db.sql`.
3. Test cleanup in `scripts/test_session_manager.py`.
4. `openspec validate remove-agent-session-redis-api --strict`.
5. Regression: rerun `scripts/test_session_manager.py` and one pipeline e2e smoke.
6. Post-deploy operator runs two one-liners (Redis DEL pattern + optional manual `DROP TABLE`).
