## 1. Tool implementation

- [x] 1.1 Create `src/tools/builtins/project_info.py` with module docstring and the three tool classes stubbed out
- [x] 1.2 Implement `GetCurrentProjectTool`: query `projects` + `documents` count + latest `workflow_runs`; format plain-text output; handle `project_id=None` error path
- [x] 1.3 Implement `ListProjectRunsTool`: input_schema with `limit` (default 10, clamp [1,50]) + optional `status`; order by `started_at DESC NULLS LAST, id DESC`; format one line per run with computed `duration_s`
- [x] 1.4 Implement `GetRunDetailsTool`: single query joining `workflow_runs` on `project_id` for ownership guard; fetch `agent_runs` rows ordered by id; extract last-assistant preview from `messages` JSONB with fallback chain (assistant → result → `(no output)`); truncate to 200 chars
- [x] 1.5 All three tools: declare `is_read_only() → True` and `is_concurrency_safe() → True`
- [x] 1.6 All three tools: uniform error output on missing `context.project_id`: `"Error: no project context available"`

## 2. Registration

- [x] 2.1 Import the three tool classes in `src/tools/builtins/__init__.py`
- [x] 2.2 Add instances to the list in `get_all_tools()`
- [x] 2.3 Verify the `/tools` REST endpoint returns the three new tools in its catalogue

## 3. Agent grants

- [x] 3.1 Add `get_current_project`, `list_project_runs`, `get_run_details` to the `tools:` list in `agents/assistant.md`
- [x] 3.2 Add the same three to `agents/coordinator.md`
- [x] 3.3 Add the same three to `agents/clawbot.md`
- [x] 3.4 Confirm no pipeline sub-role file in `agents/` lists any of the three tools

## 4. Tests

- [x] 4.1 Unit test for `GetCurrentProjectTool`: seeded project with N docs and M runs returns expected output
- [x] 4.2 Unit test for `GetCurrentProjectTool`: `project_id=None` returns error without DB query
- [x] 4.3 Unit test for `ListProjectRunsTool`: default limit, status filter, limit clamping edge cases (0, 500, -1)
- [x] 4.4 Unit test for `ListProjectRunsTool`: rows from a different project do not leak into results
- [x] 4.5 Unit test for `GetRunDetailsTool`: happy path with multiple agent_runs
- [x] 4.6 Unit test for `GetRunDetailsTool`: cross-project run_id returns not-found without revealing existence
- [x] 4.7 Unit test for `GetRunDetailsTool`: preview fallback chain (assistant present / absent / empty)
- [x] 4.8 Unit test for `GetRunDetailsTool`: preview truncation at 200 chars

## 5. Smoke test

- [ ] 5.1 Start the stack (`docker compose up -d --build api`) and open a chat session in the web UI against a project with at least one completed run
- [ ] 5.2 Ask the assistant "what project am I in and how many documents does it have?" — verify it calls `get_current_project` and answers correctly
- [ ] 5.3 Ask "list my recent runs" — verify it calls `list_project_runs` and renders the result
- [ ] 5.4 Ask "what did the last run do?" — verify it calls `list_project_runs` then `get_run_details` on the top row
