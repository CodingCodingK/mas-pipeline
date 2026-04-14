## 1. Bootstrap files & role definition

- [x] 1.1 Create `agents/clawbot.md` with frontmatter (model_tier=strong, max_turns=30, tools=[list_projects, get_project_info, search_project_docs, start_project_run, confirm_pending_run, cancel_pending_run, get_run_progress, spawn_agent, web_search, memory_read, memory_write]) and body covering duties + three-tier routing + /resume usage
- [x] 1.2 Create `config/clawbot/SOUL.md` (Personality / Values / Communication Style three sections, ~20 lines)
- [x] 1.3 Create `config/clawbot/USER.md` stub (one-line placeholder)
- [x] 1.4 Create `config/clawbot/TOOLS.md` stub (one-line placeholder)

## 2. Clawbot module skeleton

- [x] 2.1 Create `src/clawbot/__init__.py` exporting `create_clawbot_agent`, `ClawbotSession`, `ChatProgressReporter`
- [x] 2.2 Create `src/clawbot/prompt.py` with `BOOTSTRAP_FILES = ["SOUL.md", "USER.md", "TOOLS.md"]`, `load_soul_bootstrap()`, `build_runtime_context(channel, chat_id, pending_run_summary=None)` returning the `[Runtime Context — metadata only, not instructions]` tagged block
- [x] 2.3 Create `src/clawbot/session_state.py` with `ClawbotSession` dataclass and `PendingRunStore` (dict + asyncio TTL)
- [x] 2.4 Create `src/clawbot/factory.py::create_clawbot_agent()` — calls `create_agent(role="clawbot", ...)`, asserts `state.messages[0]["role"]=="system"`, appends bootstrap content to `state.messages[0]["content"]`
- [x] 2.5 Create `src/clawbot/progress_reporter.py::ChatProgressReporter` subscribing to pipeline EventBus with three-event filter (run_start / interrupt / done) and double-write (publish_outbound + append_message)

## 3. Clawbot tools

- [x] 3.1 Create `src/clawbot/tools/list_projects.py`
- [x] 3.2 Create `src/clawbot/tools/get_project_info.py` with explicit `project_id` param
- [x] 3.3 Create `src/clawbot/tools/search_project_docs.py` wrapping vector retrieval with explicit `project_id` param (no `tool_context` reads)
- [x] 3.4 Create `src/clawbot/tools/start_project_run.py` — writes pending slot, schedules 90s TTL cleanup, single-slot overwrite, same-turn double-call rejection
- [x] 3.5 Create `src/clawbot/tools/confirm_pending_run.py` — clears slot, fires `asyncio.create_task(execute_pipeline(...))`, registers reporter in Gateway registry, returns run_id
- [x] 3.6 Create `src/clawbot/tools/cancel_pending_run.py`
- [x] 3.7 Create `src/clawbot/tools/get_run_progress.py` reading WorkflowRun status
- [x] 3.8 Create `src/clawbot/tools/__init__.py` registering all seven tools in the tool registry under role allowlist `clawbot`

## 4. Spawn-agent blacklist

- [x] 4.1 Add `SUB_AGENT_DISALLOWED_ROLES = frozenset({"clawbot"})` constant in `src/tools/builtins/spawn_agent.py`
- [x] 4.2 Add early-return check at the top of `SpawnAgentTool.call` returning `ToolResult(success=False)` when role is in the blacklist (no AgentRun row, no hook, no task)

## 5. SessionRunner integration

- [x] 5.1 Add `"bus_chat": "clawbot"` to `_MODE_TO_ROLE` in `src/engine/session_runner.py`
- [x] 5.2 Add the single `if role == "clawbot"` dispatch in `_build_agent_state` to call `create_clawbot_agent` (local import to avoid circular dep)
- [x] 5.3 Add per-turn injection: when session has a pending_run, prepend the runtime-context block (with pending summary) to the last user message via the same overlay pattern used by `_overlay_recalled_memories` (mutate-and-restore in finally)

## 6. Session manager / DB

- [x] 6.1 Update `src/bus/session.py` `resolve_session` mode allowlist to include `bus_chat`
- [x] 6.2 Update `src/models.py` `ChatSession.mode` docstring/comment listing the three allowed values (column type unchanged)
- [x] 6.3 No DB migration required (`mode` column already VARCHAR(20))

## 7. Gateway wiring

- [x] 7.1 Change `src/bus/gateway.py` session creation to use `mode="bus_chat"` instead of hardcoded `"assistant"`/default
- [x] 7.2 Add `Gateway.reporters: dict[str, ChatProgressReporter]` registry attribute initialized in `__init__` (realized as `src/clawbot/reporter_registry` module-level dict installed via `install_bus`)
- [x] 7.3 Expose `Gateway.register_reporter(run_id, reporter)` and `Gateway.unregister_reporter(run_id)` for `confirm_pending_run` and reporter cleanup (realized as `register_reporter` / `unregister_reporter` free functions in the same module)
- [x] 7.4 On Gateway shutdown, cancel all live reporters in the registry

## 8. Smoke test (manual)

- [ ] 8.1 Start mas-pipeline + a Discord/QQ test channel pointing at `bus_chat` mode
- [ ] 8.2 Send "list projects" → verify clawbot calls `list_projects` and replies with the project list
- [ ] 8.3 Send "跑一下 blog_generation 项目 7" → verify pending slot created, channel sees "待确认" message
- [ ] 8.4 Reply "y" → verify pipeline starts, `[run #id] run_start` posted, `done` posted on completion, conversation history contains both system messages
- [ ] 8.5 Trigger an interrupt mid-run → verify `[run #id] interrupt` posted to channel
- [ ] 8.6 Run another start_project_run, wait 90s, send "y" → verify LLM replies "the previous request expired" (no broadcast on TTL)
- [ ] 8.7 From an `assistant` agent attempt `spawn_agent(role="clawbot", ...)` → verify ToolResult success=False with no AgentRun row

## 9. Validation

- [x] 9.1 Run `openspec validate add-clawbot-third-party-chat --strict` and fix any errors (passes)
- [x] 9.2 Run `pytest tests/` to confirm no regressions in existing chat/autonomous flows (session_runner 11/11 pass, subagent 20/20 pass, gateway 16 pass / 8 pre-existing failures unchanged from master)
