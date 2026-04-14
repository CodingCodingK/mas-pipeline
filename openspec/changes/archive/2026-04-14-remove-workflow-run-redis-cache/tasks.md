## 1. Pre-deletion verification

- [x] 1.1 Re-run `grep -rn 'hget\|hgetall' src/ web/ scripts/` and confirm zero non-test references to `workflow_run:*` reads (the audit ran this on 2026-04-14; this is a belt-and-suspenders re-check against any drift since).
- [x] 1.2 Re-run `grep -rn '_sync_to_redis\|workflow_run:' src/ scripts/ tests/` and record the exact set of lines that will be touched.

## 2. Code deletion

- [x] 2.1 Delete the `_sync_to_redis` function (`src/engine/run.py:141-152`) and its `## ── Redis sync ──` section header comment.
- [x] 2.2 Remove the `await _sync_to_redis(run)` call at the end of `create_run` (`src/engine/run.py:182`).
- [x] 2.3 Remove the `await _sync_to_redis(run)` call at the end of `update_run_status` (`src/engine/run.py:236`).
- [x] 2.4 Remove the `await _sync_to_redis(run)` call at the end of `finish_run` (`src/engine/run.py:278`).
- [x] 2.5 Remove the now-unused `get_redis` import from `src/engine/run.py` if no other symbol in the file uses it (keep `get_db`).
- [x] 2.6 Update the module docstring at the top of `src/engine/run.py` — change `"""Workflow run management: CRUD + state machine + Redis sync."""` to drop the `+ Redis sync` suffix.

## 3. Test updates

- [x] 3.1 Delete the three `redis.hgetall(f"workflow_run:...")` assertions in `scripts/test_workflow_run.py:109`, `:146`, `:177`. Keep surrounding PG assertions.
- [x] 3.2 Delete any Redis-client setup lines in `test_workflow_run.py` that become dead after 3.1 (e.g. `redis = get_redis()` if it was only used for the assertions).
- [x] 3.3 Run `python scripts/test_workflow_run.py` against the live stack and confirm the full lifecycle test still passes. (29/29 PASS)

## 4. Spec delta application (openspec validate)

- [x] 4.1 Run `openspec validate remove-workflow-run-redis-cache --strict` and confirm zero errors.
- [x] 4.2 Run `openspec show remove-workflow-run-redis-cache` (no `diff` subcommand in this CLI version) and sanity-check the proposal + spec delta match the intended behaviour.

## 5. Regression sanity

- [x] 5.1 Run `scripts/test_streaming_regression.py` (or closest Phase-2 lifecycle regression script) against the live stack; confirm no workflow_run lifecycle breakage. (11/11 PASS)
- [x] 5.2 Trigger one `blog_with_review` pipeline run via `scripts/test_e2e_smoke.py` (mock LLM) and confirm it reaches `completed` — exercises `create_run` + `update_run_status` + `finish_run` end-to-end. (approve + reject + edit + rag_ingest, 33s)

## 6. Documentation

- [x] 6.1 Update `.plan/wrap_up_checklist.md` §6.2 to mark `remove-workflow-run-redis-cache` sub-checkbox complete with implementation summary.
- [x] 6.2 Note the one-time operator cleanup command (`redis-cli --scan --pattern 'workflow_run:*' | xargs -r redis-cli DEL`) — recorded in the checklist summary line; to be surfaced in the PR description at commit time.
