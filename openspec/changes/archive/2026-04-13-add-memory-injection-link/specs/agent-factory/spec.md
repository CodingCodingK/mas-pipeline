## MODIFIED Requirements

### Requirement: create_agent builds an independent AgentState from a role file
`create_agent(role, task_description, project_id, run_id, tools_override, max_turns, abort_signal, permission_mode, parent_deny_rules)` SHALL parse `agents/{role}.md`, construct an independent AgentState with its own messages, adapter, tools, orchestrator, and permission checker. The `permission_mode` parameter SHALL be required (no default value). The optional `parent_deny_rules` parameter SHALL pass parent deny rules to the PermissionChecker.

When `project_id` is provided AND the agent's effective tool registry contains at least one memory tool (`memory_read` or `memory_write`), `create_agent` SHALL load the project's memory list via a helper `_load_memory_list(project_id, registry)` and pass the result as `memory_context` to `build_system_prompt`. The helper SHALL:

1. Probe the tool registry for `memory_read`/`memory_write` via `registry.get()` inside a `try/except KeyError`; if neither exists, return `None` immediately (agent gets no memory layer at all).
2. If `project_id is None`, return `None`.
3. Otherwise call `list_memories(project_id)` and format each row as a one-line entry that includes `type`, `name`, and `description` (content excluded to keep token cost low).
4. If the project has zero memories, return `""` (empty string) so `_memory_layer` injects the guide with an empty-state hint.
5. Otherwise return the formatted list string.

Pipeline worker agents (analyzer, exam_generator, reviewer, writer, researcher, parser, general) SHALL NOT have memory tools in their role frontmatter and SHALL therefore short-circuit to the `None` path with zero extra token cost and zero DB queries.

#### Scenario: Chat agent with memory tools loads project memory list
- **GIVEN** agents/assistant.md has `tools: [web_search, search_docs, read_file, memory_read, memory_write]`
- **AND** project 1 has two memories stored
- **WHEN** `create_agent(role="assistant", project_id=1, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** `_load_memory_list` SHALL call `list_memories(1)` and return a formatted non-empty string
- **AND** `build_system_prompt` SHALL be called with that string as `memory_context`
- **AND** the resulting system prompt SHALL contain both the `_MEMORY_GUIDE` block and the formatted list under `## Current memories`

#### Scenario: Chat agent with memory tools but empty project
- **GIVEN** agents/coordinator.md has `tools: [spawn_agent, memory_read, memory_write]`
- **AND** project 2 has no memories yet
- **WHEN** `create_agent(role="coordinator", project_id=2, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** `_load_memory_list` SHALL return `""` (empty string, not None)
- **AND** the resulting system prompt SHALL contain the `_MEMORY_GUIDE` block plus an empty-state hint

#### Scenario: Pipeline worker agent skips memory injection entirely
- **GIVEN** agents/analyzer.md has `tools: [read_file, search_docs]` (no memory tools)
- **WHEN** `create_agent(role="analyzer", project_id=1, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** `_load_memory_list` SHALL return `None` without calling `list_memories`
- **AND** `build_system_prompt` SHALL be called with `memory_context=None`
- **AND** the resulting system prompt SHALL contain zero memory-related text

#### Scenario: create_agent without project_id skips memory injection
- **WHEN** `create_agent(role="assistant", project_id=None, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** `_load_memory_list` SHALL return `None`
- **AND** no memory layer SHALL be injected regardless of the agent's tool list

#### Scenario: Create agent with role file defaults
- **GIVEN** agents/researcher.md has frontmatter `model_tier: medium, tools: [read_file, web_search]`
- **WHEN** create_agent(role="researcher", task_description="调研 Redis", permission_mode=PermissionMode.NORMAL) is called
- **THEN** the returned AgentState SHALL have:
  - adapter routed via `router.route("medium")`
  - ToolRegistry containing only read_file and web_search (spawn_agent excluded)
  - messages containing a system prompt (from build_system_prompt) and a user message with "调研 Redis"
  - tool_context with agent_id formatted as `{run_id}:researcher`

#### Scenario: Create agent with tools override
- **GIVEN** agents/writer.md has frontmatter `tools: [write_file]`
- **WHEN** create_agent(role="writer", tools_override=["read_file", "write_file"], permission_mode=PermissionMode.NORMAL) is called
- **THEN** the ToolRegistry SHALL contain read_file and write_file (override replaces frontmatter tools)

#### Scenario: Create agent shares parent abort_signal
- **WHEN** create_agent is called with an abort_signal parameter
- **THEN** the returned AgentState.tool_context.abort_signal SHALL be the same Event instance

#### Scenario: Role file not found
- **WHEN** create_agent is called with a role that has no corresponding agents/{role}.md file
- **THEN** it SHALL raise FileNotFoundError

#### Scenario: Create agent with permission rules
- **GIVEN** settings.yaml has permissions: {deny: ["bash(rm *)"]}
- **WHEN** create_agent is called with permission_mode=NORMAL
- **THEN** a PermissionChecker SHALL be created with the deny rules and registered as PreToolUse hook on the HookRunner

#### Scenario: Create agent with parent deny rules
- **WHEN** create_agent is called with parent_deny_rules=[PermissionRule("bash", "rm *", "deny")]
- **THEN** the PermissionChecker SHALL include the parent deny rules merged with settings rules

#### Scenario: Create agent with bypass mode
- **WHEN** create_agent is called with permission_mode=BYPASS
- **THEN** the PermissionChecker SHALL be created with BYPASS mode (no permission hooks registered, zero overhead)
