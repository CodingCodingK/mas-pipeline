## ADDED Requirements

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
`build_system_prompt(role_body, project_root, memory_context=None)` SHALL construct a system prompt by concatenating layers in order: identity, role, memory, skill placeholder. Each layer that returns None SHALL be skipped.

The `memory_context` parameter accepts an optional string of formatted memory content. When provided, the memory layer SHALL include it under a `# Memory` header.

#### Scenario: Identity layer includes platform info
- **WHEN** build_system_prompt is called
- **THEN** the identity layer SHALL include OS name, Python version, and project root path

#### Scenario: Role layer contains role file body
- **WHEN** build_system_prompt is called with role_body "You are a researcher."
- **THEN** the prompt SHALL contain "You are a researcher."

#### Scenario: Memory layer with content
- **WHEN** build_system_prompt is called with memory_context="User prefers dark mode.\nDeadline is May 1st."
- **THEN** the prompt SHALL contain a "# Memory" section with that content

#### Scenario: Memory layer without content
- **WHEN** build_system_prompt is called with memory_context=None
- **THEN** the memory layer SHALL contribute no content to the prompt

#### Scenario: Skill layer is empty in Phase 3
- **WHEN** build_system_prompt is called in Phase 3
- **THEN** the skill layer SHALL contribute no content to the prompt

#### Scenario: Layers are separated by section headers
- **WHEN** build_system_prompt produces output with multiple layers
- **THEN** each layer SHALL be visually separated (e.g., markdown headers or blank lines)

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
