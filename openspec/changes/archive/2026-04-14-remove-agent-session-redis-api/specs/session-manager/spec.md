## MODIFIED Requirements

### Requirement: ORM models for sessions
The system SHALL define the `Conversation` SQLAlchemy ORM model in `src/models.py` mapping to the `conversations` table.

#### Scenario: Conversation model fields
- **WHEN** Conversation model is inspected
- **THEN** it SHALL have fields: `id` (int PK), `project_id` (int FK), `messages` (JSON), `created_at`, `updated_at`

## REMOVED Requirements

### Requirement: Agent Session Redis hot storage
**Reason**: Dead code. The write path (`create_agent_session`, `append_agent_message`, `get_agent_messages`) was implemented in the 2026-04-09 `session-memory-compact` change but no caller was ever wired up. The 2026-04-14 Redis audit confirmed zero `hget`/`hgetall`/`rpush`/`lrange` references in `src/` outside the module that defines them. In addition, the design is fundamentally incompatible with the 2026-04-10 `align-compact-with-cc` refactor: compact now rewrites the front of the message history into a summary + boundary marker, which a Redis LIST can only implement as `LRANGE 0 -1` + `LTRIM` + `RPUSH` of the entire list — O(N) every compact, negating the only reason LIST was chosen. The surviving `conversations.messages` and `agent_runs.messages` JSONB columns handle append and compact as single-row rewrites at the same cost tier, which is strictly better.

**Migration**: None required at runtime — the API has no callers. After deploy, one-time operator sweep to flush orphan Redis keys:
```
redis-cli --scan --pattern 'agent_session:*' | xargs -r redis-cli DEL
```
Any future caller that truly needs a hot-path cache for agent messages should propose a new spec change with a documented reader surface and a data structure compatible with compact (i.e. not an append-only LIST).

### Requirement: Agent Session archival to PostgreSQL
**Reason**: The archival function (`archive_agent_session`) has zero callers in `src/`, and the `agent_sessions` PG table has zero rows in production (verified 2026-04-14). Sub-agent run history is already persisted in `agent_runs.messages` JSONB via the 2026-04-14 `add-subagent-data-parity` change, which is the real archival surface for agent runs. The Redis-to-PG flow specified here was never exercised.

**Migration**: None required at runtime. The `agent_sessions` PG table is dropped via `DROP TABLE IF EXISTS agent_sessions CASCADE;` added to `scripts/init_db.sql` (following the `compact_summaries` precedent). Long-running databases that skip init may drop the table manually:
```
DROP TABLE agent_sessions;
```
