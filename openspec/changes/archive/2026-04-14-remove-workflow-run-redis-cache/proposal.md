## Why

The `workflow_run:{run_id}` Redis Hash is a dead cache: `_sync_to_redis` is called from `create_run` / `update_run_status` / `finish_run`, but `grep -r 'hget\|hgetall' src/` returns zero matches. No production code reads the Hash. The cache has no TTL and grows linearly with `workflow_runs` rows (10 keys : 10 PG rows in the current live stack; 1M rows would be ~230MB orphan data).

Phase 6 Redis audit (`.plan/redis_audit_2026-04-14.md`) flagged this as one of two dead prefixes. The chosen remediation is **path A**: delete the write path entirely rather than patch with TTL. Rationale: a cache that no one reads is not a cache, it is a leak.

## What Changes

- **BREAKING** (spec only, not runtime): remove the "every state change SHALL write to Redis Hash" requirement from `pipeline-run` capability. No external consumer depends on the Hash — this is breaking for spec readers, not for any running process.
- Delete `_sync_to_redis()` helper in `src/engine/run.py` and its three call sites in `create_run` / `update_run_status` / `finish_run`.
- Remove all Redis-Hash scenarios from `openspec/specs/pipeline-run/spec.md`, and strip "and sync to Redis" / "and Redis SHALL be updated" phrases from the three CRUD requirements.
- Update `scripts/test_workflow_run.py` — delete the three `redis.hgetall("workflow_run:...")` assertions; keep the rest of the lifecycle tests intact.
- Document a one-time operational cleanup step (`redis-cli --scan --pattern 'workflow_run:*' | xargs redis-cli DEL`) in this proposal so the orphan keys left behind after deploy can be flushed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pipeline-run`: remove the "Redis sync on every state change" requirement and strip Redis-sync clauses from the three CRUD requirements (`create_run`, `update_run_status`, `finish_run`). PG remains the single source of truth; no new requirements added.

## Impact

- **Code**: `src/engine/run.py` loses ~15 lines (one helper + three call sites + one import-use of `get_redis`).
- **Tests**: `scripts/test_workflow_run.py` loses three assertions (approx. 10 lines). Other lifecycle assertions stay.
- **Spec**: `openspec/specs/pipeline-run/spec.md` loses one requirement block + edits to three CRUD requirements.
- **Runtime**: zero behavioural change. No code reads the cache, so deleting the write path cannot break any consumer.
- **Redis memory**: -232 bytes per workflow_run row after deploy + manual `DEL` sweep. Linear leak fixed at root.
- **Deployment**: no migration, no config change, no feature flag. Safe to ship in any release.
- **Out of scope**: `agent_session:*` cleanup (separate change `remove-agent-session-redis-api`); T1 idempotency (`seen_msg:*`) and T2 LLM rate-limit (`llm_quota:*`) — separate changes.
