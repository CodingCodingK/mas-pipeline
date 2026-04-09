## MODIFIED Requirements

### Requirement: create_agent builds an independent AgentState from a role file
`create_agent(role, task_description, project_id, run_id, tools_override, max_turns, abort_signal, permission_mode, parent_deny_rules)` SHALL parse `agents/{role}.md`, construct an independent AgentState with its own messages, adapter, tools, orchestrator, and permission checker. The `permission_mode` parameter SHALL be required (no default value). The optional `parent_deny_rules` parameter SHALL pass parent deny rules to the PermissionChecker.

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
