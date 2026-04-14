## ADDED Requirements

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
