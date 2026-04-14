## 1. Pre-deletion verification

- [x] 1.1 Re-grep the repo for all five function names and the type: `grep -rn 'create_agent_session\|append_agent_message\|get_agent_messages\|archive_agent_session\|_agent_session_key\|AgentSessionRecord' src/ scripts/ web/ tests/` — confirm zero non-`src/session/manager.py`, non-`src/models.py`, non-`scripts/test_session_manager.py`, non-OpenSpec hits.
- [x] 1.2 Re-grep for runtime config references: `grep -rn 'agent_ttl_hours\|agent_session:' src/ scripts/ web/` — confirm only the definitions in `config/settings.yaml:53`, `src/project/config.py:100`, `src/session/manager.py` show up.
- [x] 1.3 Spot-check PG: `psql -c 'SELECT COUNT(*) FROM agent_sessions;'` against the live stack; record the number (expected 0). If >0, pause and flag before continuing.

## 2. Code deletion — `src/session/manager.py`

- [x] 2.1 Delete the `_agent_session_key`, `create_agent_session`, `append_agent_message`, `get_agent_messages`, and `archive_agent_session` functions (roughly L67-125) and the `## ── Agent Session (Redis) ──` section header comment.
- [x] 2.2 Remove `AgentSessionRecord` from the `src.models` import line (L12); keep `Conversation`.
- [x] 2.3 Remove `get_redis` from the `src.db` import line (L11) if no other symbol in the file uses it; keep `get_db`.
- [x] 2.4 Update the module docstring L1: change `"""Session manager: Conversation (PG) + Agent Session (Redis hot → PG cold)."""` to `"""Session manager: Conversation (PG)."""`.
- [x] 2.5 Confirm `clean_orphan_messages` at L131-145 is untouched.

## 3. Code deletion — ORM, config, DB schema

- [x] 3.1 Delete the `AgentSessionRecord` class from `src/models.py:112-122`. Check for and remove any now-unused imports (`Integer`, `Text` are used elsewhere — keep them).
- [x] 3.2 Delete the `agent_ttl_hours: int = 24` field from `src/project/config.py:100`.
- [x] 3.3 Delete the `agent_ttl_hours: 24` line from `config/settings.yaml:53`.
- [x] 3.4 Delete the `agent_sessions` table definition and `idx_agent_sessions_run` index from `scripts/init_db.sql` (L143-155).
- [x] 3.5 Add `DROP TABLE IF EXISTS agent_sessions CASCADE;` to `scripts/init_db.sql` just below the existing `DROP TABLE IF EXISTS compact_summaries CASCADE;` statement (L160).

## 4. Test updates — `scripts/test_session_manager.py`

- [x] 4.1 Delete the three Agent Session test functions/blocks around L169-260: "create agent session", "append and retrieve agent messages", "archive agent session" (including the dead imports and `mock_settings.return_value.session.agent_ttl_hours = 24` setup).
- [x] 4.2 Delete any now-unused imports at the top of the file (`get_redis`, `AgentSessionRecord`, etc.).
- [x] 4.3 Run `python scripts/test_session_manager.py` against the live stack and confirm all remaining Conversation + `clean_orphan_messages` checks still pass. Record the PASS count.

## 5. Spec delta application (openspec validate)

- [x] 5.1 Run `openspec validate remove-agent-session-redis-api --strict` and confirm zero errors.
- [x] 5.2 Run `openspec show remove-agent-session-redis-api` and sanity-check the proposal + spec delta match the intended behaviour.

## 6. Regression sanity

- [x] 6.1 Run `scripts/test_streaming_regression.py` against the live stack; confirm no session lifecycle breakage.
- [x] 6.2 Run `scripts/test_workflow_run.py` to confirm the neighbor module still passes (CI canary for the recent `remove-workflow-run-redis-cache` change + this one stacked).
- [x] 6.3 Trigger one `blog_with_review` pipeline run via `scripts/test_e2e_smoke.py` (mock LLM) and confirm it reaches `completed` — exercises the full Conversation + SessionRunner surface end-to-end.

## 7. Documentation

- [x] 7.1 Update `.plan/wrap_up_checklist.md` §6.2 to mark the `remove-agent-session-redis-api` sub-checkbox complete with an implementation summary line (function names deleted, table dropped, tests passing counts).
- [x] 7.2 Record the two one-time operator cleanup commands in the checklist summary (Redis `DEL` pattern + optional manual `DROP TABLE`) for surfacing in the PR description at commit time.
