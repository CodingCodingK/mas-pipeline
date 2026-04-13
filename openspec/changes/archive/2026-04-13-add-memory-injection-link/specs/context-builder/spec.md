## MODIFIED Requirements

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

#### Scenario: Fresh conversation with no history
- **WHEN** build_messages is called with system_prompt="You are...", history=[], user_input="hello"
- **THEN** it returns `[{"role": "system", "content": "You are..."}, {"role": "user", "content": "hello"}]`

#### Scenario: Conversation with history
- **WHEN** build_messages is called with non-empty history list
- **THEN** history messages appear between system and user messages in order

#### Scenario: Runtime context appended to system prompt
- **WHEN** build_messages is called with runtime_context={"current_time": "2026-04-07 15:00", "agent_id": "agent-1"}
- **THEN** the system message content SHALL end with a Runtime Context section containing those key-value pairs

#### Scenario: No runtime context
- **WHEN** build_messages is called with runtime_context=None
- **THEN** the system message content SHALL be the unmodified system_prompt
