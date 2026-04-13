## Purpose
Parse agent role files and assemble system prompts from layered fragments (identity, role, memory, skill). Also provides OpenAI-format message assembly for the agent loop.
## Requirements
### Requirement: Role file parsing extracts frontmatter and body
`parse_role_file(path)` SHALL read a markdown file, separate YAML frontmatter (delimited by `---`) from the body, and return a tuple of (metadata dict, body string). If no frontmatter is present, metadata SHALL be an empty dict and body SHALL be the full file content.

#### Scenario: File with frontmatter
- **WHEN** parse_role_file is called with a file containing `---\ndescription: helper\nmodel_tier: medium\ntools: [read_file]\n---\nYou are a helper.`
- **THEN** it returns `({"description": "helper", "model_tier": "medium", "tools": ["read_file"]}, "You are a helper.")`

#### Scenario: File without frontmatter
- **WHEN** parse_role_file is called with a file containing only `You are a plain agent.`
- **THEN** it returns `({}, "You are a plain agent.")`

#### Scenario: Frontmatter fields available for agent factory
- **WHEN** frontmatter contains `model_tier` and `tools` fields
- **THEN** these values SHALL be extractable as `str` and `list[str]` respectively for use by create_agent (Phase 2.5)

### Requirement: System prompt is built in layers
`build_system_prompt(role_body, project_root, memory_context=None, skill_definitions=None)` SHALL construct a system prompt by concatenating layers in order: identity, role, memory, skill. Each layer that returns None SHALL be skipped.

The `memory_context` parameter has THREE-STATE semantics that distinguish agents that cannot use memory from agents that can but have no memories yet:

- `memory_context is None` — the agent has no memory tools attached (pipeline workers, and any future read-only agents). The memory layer SHALL return None and contribute zero tokens to the system prompt. This is the default for backwards compatibility with every existing call site that does not pass the parameter.
- `memory_context == ""` (empty string) — the agent has memory tools attached but the project currently has no memories. The memory layer SHALL inject the full `_MEMORY_GUIDE` behavioural guide, followed by a `## Current memories` section containing an empty-state hint that instructs the agent how to save its first memory.
- `memory_context` is a non-empty string — the agent has memory tools and the caller has formatted a list of existing memories. The memory layer SHALL inject the full `_MEMORY_GUIDE`, then a `## Current memories` section containing a drift caveat (warning that memories may be stale and SHOULD be verified against current code/data before acting on them) followed by the formatted list.

The `_MEMORY_GUIDE` constant SHALL be a CC-`memdir`-style behavioural guide adapted for project-scoped PG-backed memory (NOT a file+index). It SHALL cover: the four memory types (user, feedback, project, reference) with descriptions, `when_to_save` guidance, `body_structure` guidance, and one example each; a `What NOT to save` blacklist; a `How to save (dedup first)` rule that REQUIRES `memory_read action="list"` before `memory_write action="write"`; and a `When to use memory` section. Its total size SHALL be kept within a ~1000 token budget so that repeated injection across turns remains cheap under provider prompt caching.

#### Scenario: Identity layer includes platform info
- **WHEN** build_system_prompt is called
- **THEN** the identity layer SHALL include OS name, Python version, and project root path

#### Scenario: Role layer contains role file body
- **WHEN** build_system_prompt is called with role_body "You are a researcher."
- **THEN** the prompt SHALL contain "You are a researcher."

#### Scenario: Memory layer omitted when agent has no memory tools
- **WHEN** build_system_prompt is called with `memory_context=None`
- **THEN** the memory layer SHALL contribute zero bytes to the prompt
- **AND** neither `_MEMORY_GUIDE` text nor a `## Current memories` header SHALL appear anywhere in the output

#### Scenario: Memory layer in empty-project state
- **WHEN** build_system_prompt is called with `memory_context=""` (agent has memory tools but project has no memories)
- **THEN** the prompt SHALL contain the full `_MEMORY_GUIDE` block
- **AND** the prompt SHALL contain a `## Current memories` section with an empty-state hint directing the agent to use `memory_write` when it learns something worth keeping

#### Scenario: Memory layer with populated list
- **WHEN** build_system_prompt is called with `memory_context="- [user] senior_dev: User is a senior developer\n- [feedback] test_ratio: 填空和简答各≥30%"`
- **THEN** the prompt SHALL contain the full `_MEMORY_GUIDE` block
- **AND** the prompt SHALL contain a `## Current memories` section that includes the drift caveat (warning that memories may be stale)
- **AND** the formatted list SHALL appear inside the same `## Current memories` section

#### Scenario: Skill layer renders always-on and on-demand skills
- **WHEN** build_system_prompt is called with `skill_definitions` containing a mix of always-on and on-demand skills
- **THEN** always-on skill content SHALL be injected in full under `# Always-On Skills`
- **AND** on-demand skills SHALL be listed as a compact `<skills>` XML block under `# Available Skills`

#### Scenario: Layers are separated by section headers
- **WHEN** build_system_prompt produces output with multiple layers
- **THEN** each layer SHALL be visually separated (markdown headers or blank lines)

### Requirement: Messages are assembled in OpenAI format
`build_messages(system_prompt, history, user_input, runtime_context)` SHALL return a list of dicts: system message first, then history messages, then user message last.

Before emitting the history portion, `build_messages` SHALL scan the `history` list from the tail toward the head for the most recent message with `metadata.is_compact_boundary == True`. If such a marker is found:

1. Messages BEFORE the boundary marker SHALL NOT be emitted to the downstream model (audit-only, kept in PG for replay).
2. The boundary marker itself SHALL NOT be emitted.
3. The summary message immediately preceding the boundary marker (identified by `metadata.is_compact_summary == True`) SHALL be emitted as a normal `{"role": "user", "content": "<summary>"}` entry (metadata stripped) so the model receives the summary as its effective first user turn.
4. All messages AFTER the boundary marker SHALL be emitted unchanged in order.

If no boundary marker is present, `build_messages` SHALL emit the full history as-is (backward compatibility with pre-change sessions).

When emitting any message that has a non-empty `metadata` dict, `build_messages` SHALL strip the `metadata` field before passing to the adapter — adapters expect plain OpenAI-format dicts and should never see the `metadata` key.

#### Scenario: Fresh conversation with no history
- **WHEN** build_messages is called with system_prompt="You are...", history=[], user_input="hello"
- **THEN** it returns `[{"role": "system", "content": "You are..."}, {"role": "user", "content": "hello"}]`

#### Scenario: Conversation with history
- **WHEN** build_messages is called with non-empty history list and no compact boundary marker
- **THEN** history messages appear between system and user messages in order

#### Scenario: Runtime context appended to system prompt
- **WHEN** build_messages is called with runtime_context={"current_time": "2026-04-07 15:00", "agent_id": "agent-1"}
- **THEN** the system message content SHALL end with a Runtime Context section containing those key-value pairs

#### Scenario: No runtime context
- **WHEN** build_messages is called with runtime_context=None
- **THEN** the system message content SHALL be the unmodified system_prompt

#### Scenario: History with compact boundary slices older messages
- **WHEN** build_messages is called with a history containing 50 pre-compact messages, then a summary message with `metadata.is_compact_summary=True`, then a boundary marker with `metadata.is_compact_boundary=True`, then 10 post-compact messages
- **THEN** the returned list SHALL contain: system message, summary-as-user-message, the 10 post-compact messages, then the final user input
- **AND** the 50 pre-compact messages SHALL NOT appear in the output
- **AND** the boundary marker itself SHALL NOT appear in the output

#### Scenario: Multiple compact boundaries, only the last one takes effect
- **WHEN** the history contains two compact cycles — an older boundary at index 20 and a newer boundary at index 60
- **THEN** only messages after index 60 plus the summary paired with the index-60 boundary SHALL be emitted
- **AND** messages 0..19, the older summary, and the older boundary SHALL NOT be emitted

#### Scenario: Metadata stripped before adapter
- **WHEN** an emitted history message originally had a `metadata` field
- **THEN** the dict returned by build_messages for that message SHALL NOT contain a `metadata` key

### Requirement: General agent role file exists
An `agents/general.md` file SHALL exist with frontmatter containing description, model_tier, and tools fields, and a body containing general-purpose assistant instructions.

#### Scenario: General agent frontmatter
- **WHEN** agents/general.md is parsed
- **THEN** frontmatter SHALL contain `description`, `model_tier: medium`, and `tools: [read_file, shell]`

#### Scenario: General agent body
- **WHEN** agents/general.md body is read
- **THEN** it SHALL contain instructions for a general-purpose assistant

### Requirement: End-to-end Phase 1 verification
A verification script SHALL demonstrate the complete Phase 1 chain: parse role file → build system prompt → build messages → construct AgentState → run agent_loop → LLM calls tool → result fed back → final response.

#### Scenario: Single agent reads a file via LLM
- **WHEN** test_single_agent.py is run with a valid LLM API key
- **THEN** the agent receives a user request, the LLM decides to use read_file, the tool executes, the result is fed back, and the LLM produces a final text response

