## Purpose
Factory for constructing independent `AgentState` instances from role files. Wires together the LLM adapter, tool registry, permission checker, hook runner, skills, and (for chat agents with memory tools) the project memory list used by Path A of the two-path memory recall.
## Requirements
### Requirement: get_all_tools returns all built-in tool instances
`get_all_tools()` SHALL return a `dict[str, Tool]` mapping tool name to tool instance for all registered built-in tools.

#### Scenario: Get all tools
- **WHEN** get_all_tools is called
- **THEN** it SHALL return a dict containing at least read_file, shell, spawn_agent, task_create, task_update, task_list, task_get

### Requirement: AGENT_DISALLOWED_TOOLS defines tools unavailable to sub-agents
AGENT_DISALLOWED_TOOLS SHALL be a set containing "spawn_agent" to prevent recursive spawning.

#### Scenario: Sub-agent tool filtering
- **WHEN** create_agent builds a tool registry for a sub-agent
- **THEN** spawn_agent SHALL NOT be in the registry, even if the role file lists it

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

### Requirement: create_agent propagates mcp_manager into the tool registry when a role lists mcp_servers
When `create_agent` is called with a non-None `mcp_manager` argument, it SHALL read the role frontmatter for an optional `mcp_servers` list. When present, only MCP tools from that subset of server names SHALL be added to the agent's `ToolRegistry`. When absent, the factory SHALL fall back to `settings.mcp_default_access`: if `"all"`, include all MCP tools from the manager; otherwise include zero MCP tools.

#### Scenario: Role with explicit mcp_servers list
- **GIVEN** `agents/researcher.md` has frontmatter `mcp_servers: [github]` and MCPManager has github connected with 3 tools
- **WHEN** `create_agent(role="researcher", mcp_manager=mgr, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** the returned AgentState's ToolRegistry SHALL contain exactly those 3 github MCPTool instances
- **AND** it SHALL NOT contain MCPTool instances from any other server

#### Scenario: Role without mcp_servers, default-all
- **GIVEN** `agents/assistant.md` has no `mcp_servers` frontmatter entry
- **AND** `settings.mcp_default_access` is `"all"`
- **WHEN** `create_agent(role="assistant", mcp_manager=mgr, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** the returned ToolRegistry SHALL contain MCPTools from every connected server in mgr

#### Scenario: create_agent with mcp_manager=None
- **WHEN** `create_agent(role="writer", mcp_manager=None, permission_mode=PermissionMode.NORMAL)` is called
- **THEN** no MCPTool SHALL be added to the registry regardless of role frontmatter

#### Scenario: Role requests unknown mcp_server
- **GIVEN** `agents/writer.md` has frontmatter `mcp_servers: [nonexistent]`
- **WHEN** `create_agent(role="writer", mcp_manager=mgr, ...)` is called where mgr has no server named "nonexistent"
- **THEN** the registry SHALL contain zero MCPTools (MCPManager.get_tools silently ignores unknown names)
- **AND** create_agent SHALL NOT raise

