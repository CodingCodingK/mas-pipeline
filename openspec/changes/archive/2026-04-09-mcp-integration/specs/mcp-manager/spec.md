## ADDED Requirements

### Requirement: MCPManager manages pipeline-level MCP connections
`MCPManager` SHALL manage the lifecycle of MCP server connections at the pipeline level. Multiple agents within the same pipeline SHALL share the same MCPManager instance and its connections.

#### Scenario: Shared across agents
- **WHEN** a pipeline has 3 agents all needing MCP tools
- **THEN** all 3 agents SHALL use tools from the same MCPManager (one connection per server, not per agent)

### Requirement: MCPManager.start connects to all configured servers
`MCPManager.start(server_configs: dict)` SHALL connect to all configured MCP servers concurrently using `asyncio.gather`. Each server config SHALL specify either `command`+`args` (stdio) or `url` (HTTP). Failed servers SHALL be logged and skipped, not blocking other servers.

#### Scenario: Concurrent startup
- **WHEN** start() is called with 3 server configs
- **THEN** all 3 servers SHALL be initialized concurrently

#### Scenario: Stdio server config
- **WHEN** a server config has command="npx" and args=["-y", "server-github"]
- **THEN** MCPManager SHALL create a StdioTransport and MCPClient for that server

#### Scenario: HTTP server config
- **WHEN** a server config has url="http://localhost:3001/mcp"
- **THEN** MCPManager SHALL create an HTTPTransport and MCPClient for that server

#### Scenario: Server startup failure isolated
- **WHEN** server "github" fails to start but "postgres" succeeds
- **THEN** MCPManager SHALL log the github failure, and postgres tools SHALL still be available

### Requirement: MCPManager.get_tools returns MCPTool list
`MCPManager.get_tools(server_names: list[str] | None = None)` SHALL return MCPTool instances. If server_names is None, return tools from all connected servers. If server_names is provided, return tools only from those servers.

#### Scenario: Get all tools
- **WHEN** get_tools() is called with no arguments
- **THEN** it SHALL return MCPTool instances from all connected servers

#### Scenario: Filter by server names
- **WHEN** get_tools(["github"]) is called
- **THEN** it SHALL return only MCPTool instances from the "github" server

#### Scenario: Unknown server name ignored
- **WHEN** get_tools(["nonexistent"]) is called
- **THEN** it SHALL return an empty list (no error)

### Requirement: MCPManager.shutdown closes all connections
`MCPManager.shutdown()` SHALL call shutdown on all connected MCPClient instances. Errors during shutdown SHALL be logged but not raised.

#### Scenario: Clean shutdown
- **WHEN** shutdown() is called
- **THEN** all MCP server connections SHALL be closed

#### Scenario: Shutdown error tolerance
- **WHEN** one server's shutdown raises an exception
- **THEN** other servers SHALL still be shut down, and the exception SHALL be logged

### Requirement: MCPManager as async context manager
MCPManager SHALL support `async with` usage: `__aenter__` returns self, `__aexit__` calls shutdown.

#### Scenario: Context manager usage
- **WHEN** MCPManager is used as `async with MCPManager() as mgr`
- **THEN** shutdown SHALL be called automatically on exit, even if an exception occurred
