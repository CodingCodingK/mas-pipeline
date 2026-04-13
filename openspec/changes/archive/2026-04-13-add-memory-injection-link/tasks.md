## 1. memory-store: rename type enum (BREAKING)

- [x] 1.1 Rename `VALID_TYPES` in `src/memory/store.py:15` to `{"user", "feedback", "project", "reference"}`
- [x] 1.2 Update `scripts/test_memory_system.py` assertions (VALID_TYPES check around line 35; fixture `type="fact"` → `"user"`; write tool test payload `type="fact"` → `"user"`)
- [x] 1.3 Run `python scripts/test_memory_system.py` and confirm all assertions pass against a fresh empty `memories` table

## 2. memory-tools: enforce enum on MemoryWriteTool

- [x] 2.1 In `src/tools/builtins/memory.py` `MemoryWriteTool.input_schema`, add `"enum": ["user", "feedback", "project", "reference"]` to the `type` field
- [x] 2.2 Rewrite the `type` field's `description` to explain the semantic meaning of each of the four values (user / feedback / project / reference)
- [x] 2.3 Update the invalid-type error message to read `"Error: invalid memory type '<x>'. Valid: user, feedback, project, reference"`
- [x] 2.4 Add/update a test that writes with `type="fact"` (legacy) and asserts `success=False` + new error message

## 3. context-builder: add _MEMORY_GUIDE + 3-state _memory_layer

- [x] 3.1 Add `_MEMORY_GUIDE` constant in `src/agent/context.py` — CC-memdir-style guide adapted for PG-backed project-scoped memory, ~1000 tokens max, containing: intro paragraph with tool names, four `<type>` blocks (user/feedback/project/reference) each with `description` / `when_to_save` / `body_structure` / one example, `## What NOT to save` blacklist, `## How to save (dedup first)` rule requiring `memory_read list` before `memory_write write`, `## When to use memory` section
- [x] 3.2 Add `_MEMORY_DRIFT_CAVEAT` constant with the stale-memory warning text
- [x] 3.3 Rewrite `_memory_layer` to three-state semantics: `None` → return None; `""` → guide + `## Current memories` with empty-state hint; non-empty → guide + `## Current memories` + drift caveat + list
- [x] 3.4 Ensure `build_system_prompt` signature still accepts `memory_context: str | None = None` and defaults so all existing callers (pipeline workers, tests) remain unchanged
- [x] 3.5 Measure the guide's token size with a tokenizer; confirm it is under ~1000 tokens; record the number in a comment near the constant

## 4. agent-factory: load memory list + inject memory_context

- [x] 4.1 Add `_load_memory_list(project_id, registry)` helper in `src/agent/factory.py` returning `str | None` with three-state semantics documented in the docstring
- [x] 4.2 Implement the tool-presence probe via `try: registry.get("memory_read")` / `registry.get("memory_write")` wrapped in `except KeyError` — do NOT touch private `registry._tools`
- [x] 4.3 When both project_id and a memory tool are present, call `list_memories(project_id)` and format each row as `[<id>] (<type>) <name> -- <description>` joined by newlines
- [x] 4.4 Return `""` when list is empty, formatted string when non-empty, `None` otherwise
- [x] 4.5 In `create_agent` around line 142, call `_load_memory_list` and pass the result to `build_system_prompt(role_body, memory_context=memory_context, skill_definitions=filtered_skills)`
- [x] 4.6 Verify that calling `create_agent` for an analyzer/writer/researcher role (no memory tools) does NOT issue `list_memories` or inject any memory text

## 5. Agent role files: expose memory tools to chat agents

- [x] 5.1 Update `agents/assistant.md` frontmatter `tools:` list to include `memory_read, memory_write`
- [x] 5.2 Update `agents/coordinator.md` frontmatter `tools:` list to include `memory_read, memory_write`
- [x] 5.3 Verify pipeline worker role files (analyzer, exam_generator, reviewer, writer, researcher, parser, general) are NOT modified — they remain without memory tools

## 6. session-runner: per-turn _overlay_recalled_memories

- [x] 6.1 Add `_overlay_recalled_memories()` method on `SessionRunner` in `src/engine/session_runner.py` that returns `Callable[[], None] | None` (the restore closure, or None when overlay does not apply)
- [x] 6.2 Short-circuit: no pending user turn → None; no project_id → None; no memory tools in registry → None; `select_relevant` returns empty → None
- [x] 6.3 When applicable, call `select_relevant(project_id, query=last_user_content, limit=5)`, format selected memories as a `<recalled_memories>` XML block, MUTATE (do not insert) `state.messages[last_user_idx].content` by prepending the block to the original content
- [x] 6.4 Build and return a restore closure that captures the original content and the index, and writes the original content back on invocation
- [x] 6.5 In the main loop around line 234, call `recall_restore = await self._overlay_recalled_memories()` just before entering the `async for event in agent_loop(...)` block
- [x] 6.6 Wrap the agent_loop iteration in `try/finally`; the `finally` block SHALL invoke `recall_restore()` if it is not None, BEFORE `_persist_new_messages` runs
- [x] 6.7 Document the invariant in the method docstring: "This method assumes agent_loop only appends to state.messages and never mutates indices before last_user_idx"

## 7. End-to-end verification

- [ ] 7.1 Bring up the compose stack; create a fresh project; start a chat session against `assistant`
- [ ] 7.2 Send "以后输出都用中文，简明点" and observe the agent calls `memory_write` to save a `user` or `feedback` memory
- [ ] 7.3 End the session, start a new one on the same project; inspect the system prompt via telemetry/logs and confirm a `## Current memories` section contains the previously-written memory
- [ ] 7.4 Send a related user message and confirm that a `<recalled_memories>` overlay was applied to the turn's user message in the runner logs
- [ ] 7.5 Inspect `conversation.messages` in PG and confirm NO `<recalled_memories>` substring was persisted
- [ ] 7.6 Confirm a pipeline run (e.g., courseware) shows no memory-related log entries and no extra `list_memories` DB query

## 8. OpenSpec validation & archive

- [ ] 8.1 Run `openspec validate add-memory-injection-link --strict` and fix any errors
- [ ] 8.2 After user approval, run `/openspec-archive add-memory-injection-link` to move the change into `openspec/changes/archive/` and fold deltas back into the canonical specs
