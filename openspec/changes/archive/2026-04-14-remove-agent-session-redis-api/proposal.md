## Why

The `agent_session:{agent_id}` Redis Hash API and its PG cold-archive path are dead code. The 2026-04-14 Redis audit confirmed zero callers anywhere in `src/` outside the module that defines them, and zero rows in the `agent_sessions` PG table. The original "Redis hot → PG cold" plan is also architecturally incompatible with the current codebase after the 2026-04-10 `align-compact-with-cc` refactor: compact rewrites the front of a message history into a summary + boundary marker, which a Redis LIST can only implement as `LRANGE 0 -1` + `LTRIM` + `RPUSH` of the entire list — O(N) every compact, negating the only reason LIST was chosen. The active code path (`conversations.messages` / `agent_runs.messages` JSONB) already handles both append and compact as single-row rewrites at the same cost tier.

## What Changes

- **BREAKING (spec-only)**: Remove the "Agent Session Redis hot storage", "Agent Session archival to PostgreSQL", and the `AgentSessionRecord` portion of the "ORM models for sessions" requirements from `session-manager` spec. No runtime behavior changes because the API has no callers.
- Delete `_agent_session_key`, `create_agent_session`, `append_agent_message`, `get_agent_messages`, `archive_agent_session` from `src/session/manager.py` (~L67-125).
- Delete the `AgentSessionRecord` ORM class from `src/models.py` (L112-122).
- Delete the `agent_sessions` PG table + index from `scripts/init_db.sql` (L143-155); add `DROP TABLE IF EXISTS agent_sessions CASCADE;` following the `compact_summaries` precedent so existing deployments drop the orphan table on next `init_db` run.
- Delete the `agent_ttl_hours: int = 24` field from `src/project/config.py:100` and the corresponding entry from `config/settings.yaml:53`.
- Delete the three Agent Session test cases in `scripts/test_session_manager.py` (L169-260 approx): "create agent session", "append/get agent messages", "archive agent session". Keep Conversation and `clean_orphan_messages` test coverage untouched.
- The surviving surface (`conversations` CRUD, `clean_orphan_messages`, ChatSession / `resolve_session` / `get_session_history`) is unchanged.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `session-manager`: remove three Agent Session requirements (Redis hot storage, PG archival, AgentSessionRecord model field scenario) and drop the `AgentSessionRecord` mention from the ORM-models requirement.

## Impact

- **Code**: `src/session/manager.py` (~60 lines removed), `src/models.py` (~11 lines removed), `src/project/config.py` (1 line), `config/settings.yaml` (1 line), `scripts/init_db.sql` (~14 lines removed + DROP statement added), `scripts/test_session_manager.py` (~90 lines removed).
- **Runtime**: zero behavior change. All deletions are confirmed-unreachable code paths. The two live readers of `src.session.manager` (`SessionRunner` and `clean_orphan_messages` callers) touch only the Conversation / orphan-cleanup surface, which is unchanged.
- **Operator cleanup (one-time)**:
  - Redis: `redis-cli --scan --pattern 'agent_session:*' | xargs -r redis-cli DEL`
  - PG: handled automatically on next startup via `DROP TABLE IF EXISTS` in `init_db.sql`, or manually via `DROP TABLE agent_sessions;` for long-running DBs that skip init.
- **Specs**: `openspec/specs/session-manager/spec.md` will shrink by ~3 requirement blocks on archive.
- **Out of scope**: T1 idempotency (`seen_msg:*`) and T2 LLM rate limiting (`llm_quota:*`) remain their own follow-up changes. `chat_session:*` cache and `gateway:lock` are live and untouched. `conversations.messages` / `agent_runs.messages` JSONB columns (the real message stores) are untouched.
