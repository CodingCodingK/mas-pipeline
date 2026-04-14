## ADDED Requirements

### Requirement: Sub-agent disallowed roles blacklist
`src/tools/builtins/spawn_agent.py` SHALL define a module-level constant `SUB_AGENT_DISALLOWED_ROLES: frozenset[str] = frozenset({"clawbot"})`. On every `SpawnAgentTool.call(params, context)` invocation, the tool SHALL check `params["role"]` against this set as the first action in `call`, and if matched return `ToolResult(success=False, output="role '<role>' cannot be spawned as a sub-agent")` without creating an `AgentRun` row, without firing hook events, and without launching any task.

The check exists to prevent `clawbot` (the top-level group-chat router) from being recursively spawned by other agents — it owns its own progress-reporting and pending-run lifecycle that does not make sense inside a sub-agent context.

#### Scenario: Spawning clawbot is rejected
- **WHEN** any agent calls `spawn_agent` with `role="clawbot"`
- **THEN** the tool SHALL return `ToolResult(success=False)` with a message indicating the role is not spawnable
- **AND** no `AgentRun` row SHALL be created
- **AND** no `SubagentStart` hook SHALL fire
- **AND** no `asyncio.create_task` SHALL be launched

#### Scenario: Other roles still spawn normally
- **WHEN** any agent calls `spawn_agent` with `role="researcher"`
- **THEN** the existing spawn path SHALL execute unchanged (AgentRun created, hook fires, task launched)

#### Scenario: Blacklist is a single source of truth
- **WHEN** future roles need to be added to the blacklist
- **THEN** they SHALL be added to `SUB_AGENT_DISALLOWED_ROLES` and no other code path SHALL need updating
