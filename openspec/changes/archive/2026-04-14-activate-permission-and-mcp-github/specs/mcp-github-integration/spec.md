## ADDED Requirements

### Requirement: config/settings.yaml ships a github MCP server entry
`config/settings.yaml` SHALL include an `mcp_servers.github` entry with stdio transport configuration:
- `command`: `"npx"`
- `args`: `["-y", "@modelcontextprotocol/server-github"]`
- `env.GITHUB_PERSONAL_ACCESS_TOKEN`: `"${GITHUB_PAT}"` (environment variable substitution)

#### Scenario: Default settings include github server config
- **WHEN** `load_settings()` is called with no local overrides
- **THEN** `settings.mcp_servers["github"]` SHALL be a dict with `command`, `args`, and `env` keys
- **AND** `settings.mcp_servers["github"]["command"]` SHALL equal `"npx"`

#### Scenario: GITHUB_PAT env var is substituted
- **GIVEN** `GITHUB_PAT` environment variable is set to `"ghp_xxx"`
- **WHEN** settings are loaded
- **THEN** `settings.mcp_servers["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"]` SHALL equal `"ghp_xxx"`

#### Scenario: Missing GITHUB_PAT is tolerated
- **GIVEN** `GITHUB_PAT` environment variable is unset
- **WHEN** settings are loaded
- **THEN** settings loading SHALL succeed (no exception)
- **AND** MCPManager.start SHALL log a warning and skip the github server without raising

### Requirement: SessionRunner owns an MCPManager lifecycle
`SessionRunner.start()` SHALL instantiate an `MCPManager` and invoke `await manager.start(settings.mcp_servers)` before creating the agent state. `SessionRunner.stop()` SHALL invoke `await manager.shutdown()` after the main loop task completes.

#### Scenario: MCP manager started on session start
- **WHEN** a SessionRunner is started
- **THEN** it SHALL create an MCPManager instance and call `start(settings.mcp_servers)` before `create_agent`
- **AND** the MCPManager SHALL be passed as `mcp_manager=...` to `create_agent`

#### Scenario: MCP manager shut down on session stop
- **WHEN** a SessionRunner stops (idle timeout, graceful exit, or error)
- **THEN** it SHALL invoke `await self.mcp_manager.shutdown()` so that subprocess MCP servers are terminated

#### Scenario: MCP startup failure does not break session
- **GIVEN** `settings.mcp_servers.github` is configured but the PAT is invalid
- **WHEN** SessionRunner starts
- **THEN** MCPManager SHALL log the failure and continue
- **AND** the SessionRunner SHALL still start successfully with zero MCP tools available
- **AND** the agent SHALL still have all builtin tools

### Requirement: researcher role requests github MCP server via metadata
`agents/researcher.md` SHALL include a frontmatter entry `mcp_servers: [github]` so that `create_agent` registers only the github MCP tools into the researcher's tool registry.

#### Scenario: Researcher agent gets github tools
- **GIVEN** `agents/researcher.md` has `mcp_servers: [github]` and the github server is connected
- **WHEN** `create_agent(role="researcher", mcp_manager=mgr, ...)` is called
- **THEN** the returned `AgentState.tools` SHALL contain at least one MCPTool whose server_name is `"github"`

#### Scenario: Non-researcher agents skip github tools even when manager is passed
- **GIVEN** `agents/writer.md` has NO `mcp_servers` frontmatter entry
- **WHEN** `create_agent(role="writer", mcp_manager=mgr, ...)` is called
- **AND** `settings.mcp_default_access` is `"all"` (default)
- **THEN** per current factory behavior the writer SHALL receive all available MCP tools (writer still benefits from default-all, only roles that explicitly list `mcp_servers` get filtered)

### Requirement: config/settings.local.yaml.example documents GITHUB_PAT
`config/settings.local.yaml.example` SHALL contain a commented section showing how to provision `GITHUB_PAT` via environment variable, including a note about required PAT scope (`public_repo` minimum for search + file reads) and a warning not to commit the real token.

#### Scenario: Example file documents github PAT
- **WHEN** `config/settings.local.yaml.example` is read
- **THEN** it SHALL contain the string `GITHUB_PAT` and the string `public_repo`
