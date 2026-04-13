## ADDED Requirements

### Requirement: Per-turn memory recall overlay on the last user message
Before entering each `agent_loop` turn, `SessionRunner` SHALL call an internal helper `_overlay_recalled_memories()` that uses the existing `src/memory/selector.py` light-tier LLM selector to pick the most relevant project memories for the current user query and temporarily attach their full content to the last user message for the duration of one turn. The overlay SHALL NOT be persisted to PG.

The overlay mechanism SHALL use CONTENT MUTATION of the existing last user message (NOT list insertion of a new message), so that `state.messages` length remains unchanged and the `_pg_synced_count` position counter used by `_persist_new_messages` remains correct. The helper SHALL:

1. Short-circuit and return `None` when any of the following is true: there is no pending user turn, the runner has no `project_id`, the agent is not a chat agent with memory tools, or the project has zero memories.
2. Otherwise call `select_relevant(project_id, query=<last user message content>, limit=5)` to fetch at most 5 relevant full-content `Memory` objects. If the selector returns an empty list, return `None` without mutating state.
3. Format the selected memories as a `<recalled_memories>` XML block containing one `<memory>` child per entry (with `type`, `name`, `description`, full `content`).
4. Capture the original `content` of `state.messages[last_user_idx]`, then overwrite it with the `<recalled_memories>` block PREPENDED to the original content.
5. Return a `restore` callable (closure) that, when invoked, writes the original content back into `state.messages[last_user_idx]`.

The runner's main loop SHALL call this helper immediately before entering `agent_loop` and SHALL invoke the returned `restore` callable in a `finally` block so that the original user message is restored even if `agent_loop` raises. `_persist_new_messages` SHALL only run AFTER the finally block has executed, guaranteeing that PG never sees the overlaid content.

#### Scenario: Overlay prepends recalled memories to last user message
- **GIVEN** a chat SessionRunner for a project that has 3 memories
- **AND** the user has just sent "帮我生成一份期末试卷"
- **AND** `select_relevant` returns 2 memories (one `feedback` about question ratios, one `project` about the current textbook)
- **WHEN** the runner enters its next turn
- **THEN** `_overlay_recalled_memories` SHALL mutate the last user message's content to begin with a `<recalled_memories>` block containing both memories
- **AND** the original user query text SHALL appear after the block inside the same content field
- **AND** `state.messages` SHALL have the same length as before the call

#### Scenario: Restore runs after agent_loop completes normally
- **WHEN** the runner finishes a turn after an overlay was applied
- **THEN** the `finally` block SHALL invoke `restore()` before `_persist_new_messages` is called
- **AND** `state.messages[last_user_idx].content` SHALL equal the original unmodified user text
- **AND** the row appended to `Conversation.messages` SHALL NOT contain any `<recalled_memories>` substring

#### Scenario: Restore runs even when agent_loop raises
- **WHEN** `agent_loop` raises an exception mid-turn after an overlay was applied
- **THEN** the `finally` block SHALL still invoke `restore()`
- **AND** `state.messages[last_user_idx].content` SHALL be restored to the original user text before the exception propagates

#### Scenario: Empty project short-circuits without LLM call
- **GIVEN** the project has zero memories
- **WHEN** the runner enters a turn
- **THEN** `_overlay_recalled_memories` SHALL return `None` without calling `select_relevant`
- **AND** zero light-tier LLM calls SHALL be issued for memory selection
- **AND** the finally block's restore SHALL be a no-op

#### Scenario: Pipeline worker session skips overlay
- **GIVEN** a SessionRunner running an agent role without memory tools
- **WHEN** the runner enters a turn
- **THEN** `_overlay_recalled_memories` SHALL return `None` without calling the selector
- **AND** zero DB queries and zero LLM calls SHALL be issued for memory recall

#### Scenario: Selector returns empty result short-circuits overlay
- **GIVEN** the project has memories but `select_relevant` returns an empty list for the current query
- **WHEN** the runner enters a turn
- **THEN** `_overlay_recalled_memories` SHALL return `None`
- **AND** `state.messages[last_user_idx].content` SHALL remain unchanged
