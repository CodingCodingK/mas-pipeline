## Context

The `workflow_run:{run_id}` Redis Hash was introduced in the 2026-04-08 `workflow-run` change as a "hot-path cache" for run status/timestamps, intended to be read by the bus gateway and session-routing layer. That reader side was never implemented. Phase 6.1 Redis audit (2026-04-14) confirmed:

- `src/engine/run.py:_sync_to_redis` writes five string fields per state change.
- `grep -rn 'hget\|hgetall' src/` returns zero hits. Only `scripts/test_workflow_run.py` reads the Hash, and only to assert that the write path wrote what it said it would.
- The Hash has no TTL; keys accumulate 1:1 with `workflow_runs` rows.

PG remains authoritative. Every code path that needs run status/timestamps reads from `WorkflowRun` via SQLAlchemy, not Redis. Removing the write path has zero runtime consumer impact.

## Goals / Non-Goals

**Goals:**
- Delete the dead Redis write path so the leak stops at the source.
- Keep `pipeline-run` spec honest — a spec should not describe a behaviour the codebase does not need.
- Preserve every PG-side invariant in `create_run` / `update_run_status` / `finish_run` exactly.

**Non-Goals:**
- Introducing a replacement cache. There is no evidence `workflow_runs` reads are a hot path; the benchmark layer (§5.1.c) hits PG directly and has never flagged run lookups as slow.
- Touching `agent_session:*` — handled in a sibling change.
- Touching any other Redis usage (`chat_session:*`, `gateway:lock`).

## Decisions

### D1: Delete the write path (Path A), not add a TTL (Path B)

**Choice**: remove `_sync_to_redis` and all three call sites entirely.

**Alternative considered**: keep `_sync_to_redis` and add `await redis.expire(key, 7*24*3600)` at the end.

**Why A**: Path B preserves a code path whose sole effect is to write data that nothing reads. "Good code has no useless branches." A self-expiring cache no-one reads is still a cache no-one reads — Path B hides the symptom (unbounded growth) without fixing the disease (dead code). Path A is a strictly smaller codebase and removes one source of PG/Redis write amplification (three extra network round-trips per run lifecycle).

### D2: Remove the spec requirement outright, do not replace with a negative requirement

**Choice**: delete the "Redis sync on every state change" requirement from `pipeline-run/spec.md` and strip "and sync to Redis" clauses from the three CRUD requirements. Do not add a "SHALL NOT cache run state in Redis" anti-requirement.

**Alternative considered**: add a negative requirement to pin the decision into spec form so a future contributor cannot silently re-add a cache.

**Why delete**: shorter diff, cleaner spec. The proposal/design.md of this change IS the durable record of why we removed the cache; anyone considering re-adding it will find this change in `openspec/changes/archive/` and read the rationale. OpenSpec's archive trail is the right place for "why we went the other way" commentary, not a negative requirement in the live spec.

### D3: Do not add a feature flag or staged rollout

Pure deletion of an unread write path cannot break runtime. No flag, no canary, no A/B. A single PR lands the whole change.

## Risks / Trade-offs

- **[Risk] Hidden reader surfaces post-deletion** → Mitigation: task T1 re-runs `grep -rn 'hget\|hgetall\|workflow_run:' src/ scripts/ tests/ web/` as a belt-and-suspenders check immediately before code deletion. The audit already ran this in October; task T1 re-verifies against any changes since.
- **[Risk] Test regressions in `test_workflow_run.py`** → Mitigation: task T3 rewrites the three hgetall assertions into PG-only assertions (the PG side is already asserted in the same test; the Redis lines are additive and can be dropped without losing lifecycle coverage).
- **[Trade-off] Orphan `workflow_run:*` keys in live Redis** → After deploy, 10 existing keys persist. Operator runs `redis-cli --scan --pattern 'workflow_run:*' | xargs -r redis-cli DEL` once. Documented in the proposal Impact section. Not in the tasks list because it is an operational action on deployed infra, not a code change.
- **[Trade-off] Future contributor re-adds a cache without reading history** → Accepted. OpenSpec archive is the durable rationale store. If this happens in practice we can revisit by adding a negative spec requirement then.

## Migration Plan

No data migration. No schema change. No config change. Ship in a single PR:

1. Land the code deletion + test updates + spec delta together.
2. Deploy.
3. Operator runs the one-time `redis-cli DEL` sweep.
4. Confirm `redis-cli KEYS 'workflow_run:*'` returns empty.

**Rollback**: `git revert` the commit. Redis emptiness is a safe state for a no-reader cache; rollback restores the write path but cannot break anything either.
