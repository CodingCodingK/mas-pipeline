## ADDED Requirements

### Requirement: SessionRunner instantiates and owns an MCPManager
When `SessionRunner.start()` runs, it SHALL instantiate a fresh `MCPManager()` and `await manager.start(settings.mcp_servers)` before calling `create_agent`. The manager SHALL be stored on `self.mcp_manager` and passed as the `mcp_manager=` argument to `create_agent`. When `SessionRunner.stop()` runs (graceful exit, idle timeout, or error path in the `try/finally` block that guarantees registry cleanup), it SHALL `await self.mcp_manager.shutdown()` to terminate subprocess MCP servers.

#### Scenario: MCP manager constructed on start
- **WHEN** SessionRunner.start() is invoked
- **THEN** a new MCPManager SHALL be constructed and `.start(settings.mcp_servers)` SHALL be awaited before `create_agent`
- **AND** `create_agent` SHALL be called with `mcp_manager=self.mcp_manager`

#### Scenario: MCP manager shutdown on stop
- **WHEN** SessionRunner.stop() runs through its graceful exit path
- **THEN** `self.mcp_manager.shutdown()` SHALL be awaited before the runner returns control

#### Scenario: MCP startup failure is non-fatal
- **GIVEN** settings.mcp_servers contains a server whose subprocess fails to start
- **WHEN** SessionRunner.start() runs
- **THEN** SessionRunner SHALL still complete startup (MCPManager.start already logs-and-skips failures)
- **AND** the main agent loop SHALL begin normally with zero MCP tools from the failed server

#### Scenario: Both chat and autonomous modes get MCPManager
- **WHEN** SessionRunner is started for either `chat` or `autonomous` mode
- **THEN** the MCPManager lifecycle SHALL be identical in both modes (no mode-specific branching)
