## ADDED Requirements

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
`create_agent(role, task_description, project_id, run_id, ...)` SHALL parse `agents/{role}.md`, construct an independent AgentState with its own messages, adapter, tools, and orchestrator.

#### Scenario: Create agent with role file defaults
- **GIVEN** agents/researcher.md has frontmatter `model_tier: medium, tools: [read_file, web_search]`
- **WHEN** create_agent(role="researcher", task_description="调研 Redis") is called
- **THEN** the returned AgentState SHALL have:
  - adapter routed via `router.route("medium")`
  - ToolRegistry containing only read_file and web_search (spawn_agent excluded)
  - messages containing a system prompt (from build_system_prompt) and a user message with "调研 Redis"
  - tool_context with agent_id formatted as `{run_id}:researcher`

#### Scenario: Create agent with tools override
- **GIVEN** agents/writer.md has frontmatter `tools: [write_file]`
- **WHEN** create_agent(role="writer", tools_override=["read_file", "write_file"]) is called
- **THEN** the ToolRegistry SHALL contain read_file and write_file (override replaces frontmatter tools)

#### Scenario: Create agent shares parent abort_signal
- **WHEN** create_agent is called with an abort_signal parameter
- **THEN** the returned AgentState.tool_context.abort_signal SHALL be the same Event instance

#### Scenario: Role file not found
- **WHEN** create_agent is called with a role that has no corresponding agents/{role}.md file
- **THEN** it SHALL raise FileNotFoundError
