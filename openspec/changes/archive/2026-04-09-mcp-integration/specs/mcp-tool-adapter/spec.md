## ADDED Requirements

### Requirement: MCPTool wraps MCP server tool as Tool interface
`MCPTool` SHALL be a subclass of `Tool` that wraps a single MCP server tool. It SHALL store the server name, original tool name, tool description, input schema, and a reference to the MCPClient.

#### Scenario: MCPTool properties
- **WHEN** MCPTool is created for server "github" tool "create_issue"
- **THEN** MCPTool.name SHALL be "mcp__github__create_issue"
- **AND** MCPTool.description SHALL be the description from MCP server
- **AND** MCPTool.input_schema SHALL be the inputSchema from MCP server

### Requirement: Three-part naming convention
MCPTool.name SHALL follow the format `mcp__{server_name}__{tool_name}` to avoid collisions with built-in tools and between different MCP servers.

#### Scenario: Name format
- **WHEN** server name is "postgres" and tool name is "query"
- **THEN** MCPTool.name SHALL be "mcp__postgres__query"

#### Scenario: No collision with built-in tools
- **WHEN** an MCP server exposes a tool named "read_file"
- **THEN** it SHALL be registered as "mcp__servername__read_file", not conflicting with built-in "read_file"

### Requirement: MCPTool.call forwards to MCP server
`MCPTool.call(params, context)` SHALL call `MCPClient.call_tool(original_name, params)` and return a `ToolResult`. On success, output SHALL be the result text. On MCP error, success SHALL be False.

#### Scenario: Successful tool call
- **WHEN** MCPTool.call is invoked with valid params
- **THEN** it SHALL forward to the MCP server using the original tool name and return ToolResult(output=result, success=True)

#### Scenario: MCP server error
- **WHEN** MCPClient.call_tool raises an exception
- **THEN** MCPTool.call SHALL return ToolResult(output=error_message, success=False)

### Requirement: MCPTool is not concurrency safe by default
MCPTool.is_concurrency_safe() SHALL return False (conservative default, as MCP server behavior is unknown).

#### Scenario: Default concurrency safety
- **WHEN** MCPTool.is_concurrency_safe() is called
- **THEN** it SHALL return False

### Requirement: create_mcp_tools builds MCPTool list from client
`create_mcp_tools(server_name: str, client: MCPClient)` SHALL call `client.list_tools()` and return a list of MCPTool instances, one per tool.

#### Scenario: Create tools from server
- **WHEN** create_mcp_tools is called for server "github" and the server exposes 3 tools
- **THEN** it SHALL return 3 MCPTool instances with correct three-part names
