## MODIFIED Requirements

### Requirement: create_agent builds an independent AgentState from a role file
`create_agent(role, task_description, project_id, run_id, tools_override, max_turns, abort_signal, permission_mode, parent_deny_rules)` SHALL parse `agents/{role}.md`, construct an independent AgentState with its own messages, adapter, tools, orchestrator, and permission checker. It SHALL load skills from `skills/` directory, filter by role frontmatter `skills` field, pass filtered skills to `build_system_prompt`, and register SkillTool if the agent has on-demand skills.

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

#### Scenario: Create agent with skills whitelist
- **GIVEN** agents/researcher.md has frontmatter `skills: [research]` and skills/research.md exists
- **WHEN** create_agent is called
- **THEN** the system prompt SHALL contain the research skill in the skill layer
- **AND** SkillTool SHALL be registered in ToolRegistry with available_skills containing only "research"

#### Scenario: Create agent with no skills field
- **GIVEN** agents/writer.md has no `skills` field in frontmatter
- **WHEN** create_agent is called
- **THEN** no skills SHALL be injected into the system prompt and SkillTool SHALL NOT be registered

#### Scenario: Create agent with always-on skill
- **GIVEN** agents/coder.md has frontmatter `skills: [code_style]` and skills/code_style.md has always=true
- **WHEN** create_agent is called
- **THEN** the system prompt SHALL contain the full content of code_style skill
- **AND** SkillTool SHALL NOT be registered (no on-demand skills)
