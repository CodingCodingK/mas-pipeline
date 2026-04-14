## 1. Schema migration

- [x] 1.1 Add `messages JSONB DEFAULT '[]'::jsonb NOT NULL`, `tool_use_count INT DEFAULT 0 NOT NULL`, `total_tokens INT DEFAULT 0 NOT NULL`, `duration_ms INT DEFAULT 0 NOT NULL` to `AgentRun` ORM model in `src/models.py`
- [x] 1.2 Append idempotent `ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS ...` for all four columns in `scripts/init_db.sql`
- [x] 1.3 Verify `scripts/init_db.py` (or equivalent bootstrap) picks up the new columns on a fresh DB

## 2. Agent layer — state + loop accumulation

- [x] 2.1 Add `tool_use_count: int = 0` and `cumulative_tokens: int = 0` fields to `AgentState` in `src/agent/state.py`
- [x] 2.2 In `src/agent/loop.py:agent_loop`, after each successful turn's tool dispatch, increment `state.tool_use_count += len(tool_calls)` and `state.cumulative_tokens += (usage.total_tokens or 0)` alongside the existing `state.turn_count += 1`
- [x] 2.3 Define `AgentRunResult` dataclass in `src/agent/loop.py` (or `src/agent/state.py`) with fields: `exit_reason: ExitReason`, `messages: list[dict]`, `final_output: str`, `tool_use_count: int`, `cumulative_tokens: int`, `duration_ms: int`
- [x] 2.4 Change `run_agent_to_completion(state) -> AgentRunResult`: wrap the generator consumption in `time.monotonic()`, extract final output via `extract_final_output(state.messages)`, package into `AgentRunResult`
- [x] 2.5 Make `extract_final_output` accessible from `src/agent/loop.py` (currently lives in `src/tools/builtins/spawn_agent.py`) — either import it there or move the helper into `src/agent/loop.py` / `src/agent/context.py`

## 3. Runs layer — persistence signature

- [x] 3.1 Update `complete_agent_run` in `src/agent/runs.py` to accept `messages: list[dict], tool_use_count: int, total_tokens: int, duration_ms: int` and write them to the new columns
- [x] 3.2 Update `fail_agent_run` in `src/agent/runs.py` with the same four new parameters
- [x] 3.3 Verify type hints, default values, and existing tests — no default parameter values; callers MUST pass explicitly to avoid silently zero-ing data

## 4. Call sites — spawn_agent path

- [x] 4.1 In `src/tools/builtins/spawn_agent.py:_run_agent_background`, after `run_agent_to_completion` returns, unpack the `AgentRunResult` fields
- [x] 4.2 Pass `messages`, `tool_use_count`, `cumulative_tokens`, `duration_ms` to `complete_agent_run` / `fail_agent_run` in all three exit branches (completed, max_turns, error/abort)
- [x] 4.3 Extend `format_task_notification` signature to accept `tool_use_count`, `total_tokens`, `duration_ms` and render the three new `<tool-use-count>` / `<total-tokens>` / `<duration-ms>` fields in the canonical XML order (between `<status>` and `<result>`)
- [x] 4.4 Extend `_build_notification_message` to include `tool_use_count`, `total_tokens`, `duration_ms` keys in the message's `metadata` dict (so the frontend can render badges without re-parsing XML)
- [x] 4.5 Ensure the unhandled-exception branch still calls `fail_agent_run` with whatever `state.messages` / counters accumulated before the crash (best-effort)

## 5. Call sites — pipeline path

- [x] 5.1 In `src/engine/pipeline.py:_run_node`, replace the direct `state.messages` / `state.exit_reason` lookups with destructuring from `AgentRunResult`
- [x] 5.2 Pass the four new fields to `complete_agent_run` (success + max_turns branches) and `fail_agent_run` (error branch + exception catch branch)
- [x] 5.3 Ensure the `extract_final_output` import site still works (it's now imported from the agent layer, not from `spawn_agent`)

## 6. REST API — new endpoint

- [x] 6.1 Add `GET /api/agent-runs/{id}` handler in `src/api/runs.py`, returning a full `AgentRunDetail` Pydantic model containing the existing fields + `messages`, `tool_use_count`, `total_tokens`, `duration_ms`, `run_id`
- [x] 6.2 Define `AgentRunDetail` Pydantic model alongside `AgentRunItem`; `AgentRunItem` MUST continue to exclude `messages` (list endpoint performance)
- [x] 6.3 Extend existing `AgentRunItem` model with `tool_use_count`, `total_tokens`, `duration_ms` (these are cheap INT fields, include in list view for inline badges)
- [x] 6.4 Return HTTP 404 `{"detail": "agent run not found"}` on missing id
- [x] 6.5 Verify X-API-Key auth applies (endpoint is under `/api/` prefix)

## 7. Backend tests

- [ ] 7.1 New `scripts/test_agent_run_persistence.py`:
  - Unit: `complete_agent_run` + `fail_agent_run` write all four new columns correctly
  - Integration: spawn a sub-agent via `spawn_agent`, assert the agent_run row has non-empty messages + non-zero statistics
  - Integration: run a tiny pipeline (single linear node), assert the node's agent_run row has messages + statistics
  - Assert: statistics match `state.tool_use_count` and `state.cumulative_tokens` after the loop
- [x] 7.2 New `scripts/test_task_notification_format.py`:
  - `format_task_notification` produces all six fields in the correct order
  - Failed notification still has the three statistics fields (possibly 0)
  - `_build_notification_message` metadata dict contains the three new keys
- [ ] 7.3 New `scripts/test_agent_runs_rest.py`:
  - GET /api/agent-runs/{id} returns all fields
  - GET for non-existent id returns 404
  - List endpoint still excludes `messages` (backward compat)
  - List endpoint includes `tool_use_count / total_tokens / duration_ms`
- [ ] 7.4 Extend existing `scripts/test_spawn_agent.py` to assert statistics are non-zero after a completed sub-agent
- [ ] 7.5 Extend existing `scripts/test_pipeline_*` tests to assert node agent_runs have statistics
- [x] 7.6 Run full regression: `test_agent_loop.py`, `test_compact.py`, `test_session_runner.py`, `test_bus_session_runner_integration.py` all pass with the new `AgentRunResult` return type
- [x] 7.7 Verify main agent has no accessor to `agent_runs.messages` — grep asserts no import of `agent_runs.messages` in any context builder / tool / prompt code

## 8. Frontend — shared drawer component

- [x] 8.1 Add `AgentRunDetail` type in `web/src/api/types.ts` matching the REST response
- [x] 8.2 Add `client.get<AgentRunDetail>('/agent-runs/{id}')` helper (or inline call) via the existing `src/api/client.ts`
- [x] 8.3 Create `web/src/components/AgentRunDetailDrawer.tsx`:
  - Props: `{ agentRunId: number | null; onClose: () => void }`
  - Self-contained MessageRow renderer (role-colored backgrounds, tool_calls inline) — did not extract convertHistoryMessages, chose a simpler dedicated renderer
  - Close on Escape / click-outside / close button; AbortController cancels in-flight request on unmount
  - Handles loading / 404 / network errors with dedicated UI states

## 9. Frontend — chat entry point

- [x] 9.1 `TaskNotificationPart` in `web/src/chat/ChatThread.tsx` role text is now a clickable button that opens the drawer
- [x] 9.2 Drawer state owned by shared `AgentRunDrawerProvider` context (no per-page `drawerAgentRunId` state — context provider pattern)
- [x] 9.3 Click reads `data.agent_run_id` from the assistant-ui data part (threaded through `convertHistoryMessages` in §9 backend wiring)
- [x] 9.4 `ChatPage.tsx` wraps content with `<AgentRunDrawerProvider>` — drawer mounted inside provider once
- [x] 9.5 Three stat badges (tools / tokens / duration) rendered inline on the task_notification card header

## 10. Frontend — pipeline run entry point

- [x] 10.1 `RunDetailPage` already fetches `/runs/{run_id}/agents` into `agentRuns` state; no new lookup needed — just used existing data
- [x] 10.2 Each row in the Agent Runs table opens the drawer via `openAgentRunDrawer(ar.id)` (direct id, simpler than role-lookup)
- [x] 10.3 Wrapped `RunDetailPage` default export with `<AgentRunDrawerProvider>`; inner component uses `useAgentRunDrawer()`
- [x] 10.4 Agent Runs table now has `Tools`, `Tokens`, `Duration` columns using `formatTokensCompact` / `formatDurationCompact`
- [x] 10.5 Every row in the Agent Runs table corresponds to a real agent run (the list endpoint only returns persisted rows), so no gating needed

## 11. Docs + validation

- [ ] 11.1 Update `.plan/progress.md` with an entry summarizing Phase 8.6 `add-subagent-data-parity`
- [ ] 11.2 Check off `.plan/wrap_up_checklist.md` items that this change addresses (partial overlap with 收尾 8.x)
- [x] 11.3 `openspec validate add-subagent-data-parity --strict` passes
- [ ] 11.4 Manual smoke: start docker compose stack, trigger a chat session that uses `spawn_agent`, open the task_notification card in the UI, verify the drawer shows full transcript + stats
- [ ] 11.5 Manual smoke: run `blog_with_review` pipeline, open `RunDetailPage`, click a node, verify drawer shows transcript + stats
- [ ] 11.6 Archive via `openspec archive add-subagent-data-parity` after user review
