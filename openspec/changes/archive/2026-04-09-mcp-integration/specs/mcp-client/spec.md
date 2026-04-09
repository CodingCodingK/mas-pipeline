## ADDED Requirements

### Requirement: MCPTransport abstract interface
`MCPTransport` SHALL be an ABC with methods: `start()` (async, establish connection), `send(message: dict) -> dict` (async, send JSON-RPC request and return response), `close()` (async, tear down connection).

#### Scenario: Transport interface contract
- **WHEN** a concrete transport implements MCPTransport
- **THEN** it SHALL provide async start(), send(), and close() methods

### Requirement: StdioTransport spawns subprocess
`StdioTransport(command, args, env)` SHALL spawn a subprocess using `asyncio.create_subprocess_exec`, communicate via stdin/stdout using line-delimited JSON. The `env` parameter SHALL be merged with the current process environment (os.environ).

#### Scenario: Spawn stdio server
- **WHEN** StdioTransport is started with command="npx" args=["-y", "@modelcontextprotocol/server-github"]
- **THEN** it SHALL spawn the subprocess and be ready to send/receive JSON-RPC messages

#### Scenario: Environment variable passthrough
- **WHEN** StdioTransport is started with env={"GITHUB_TOKEN": "abc123"}
- **THEN** the subprocess SHALL receive GITHUB_TOKEN in its environment merged with os.environ

#### Scenario: Close kills subprocess
- **WHEN** StdioTransport.close() is called
- **THEN** the subprocess SHALL be terminated and resources released

### Requirement: HTTPTransport connects to remote server
`HTTPTransport(url)` SHALL send JSON-RPC requests via HTTP POST to the given URL. Response SHALL be parsed as JSON.

#### Scenario: Send request to HTTP server
- **WHEN** HTTPTransport sends a JSON-RPC request to http://localhost:3001/mcp
- **THEN** it SHALL POST the JSON body and return the parsed JSON response

#### Scenario: Close cleans up HTTP client
- **WHEN** HTTPTransport.close() is called
- **THEN** HTTP client resources SHALL be released

### Requirement: MCPClient implements MCP protocol
`MCPClient(transport: MCPTransport)` SHALL implement the MCP protocol lifecycle: initialize handshake, tools/list discovery, tools/call invocation, and shutdown.

#### Scenario: Initialize handshake
- **WHEN** MCPClient.initialize() is called
- **THEN** it SHALL send `initialize` request with protocol version and client capabilities, wait for response, then send `initialized` notification

#### Scenario: List tools
- **WHEN** MCPClient.list_tools() is called after successful initialize
- **THEN** it SHALL send `tools/list` request and return a list of tool definitions (name, description, inputSchema)

#### Scenario: Call tool
- **WHEN** MCPClient.call_tool(name, arguments) is called
- **THEN** it SHALL send `tools/call` request with the tool name and arguments, and return the result content as a string

#### Scenario: Call tool returns error
- **WHEN** MCP server returns isError=true in tools/call response
- **THEN** MCPClient.call_tool SHALL raise an exception with the error message

#### Scenario: Shutdown
- **WHEN** MCPClient.shutdown() is called
- **THEN** it SHALL send shutdown request, wait for response, send exit notification, and close the transport

### Requirement: JSON-RPC 2.0 message format
All messages SHALL follow JSON-RPC 2.0 format: requests have `{jsonrpc: "2.0", method, params, id}`, responses have `{jsonrpc: "2.0", result/error, id}`, notifications have `{jsonrpc: "2.0", method, params}` (no id).

#### Scenario: Request ID matching
- **WHEN** MCPClient sends a request with id=1
- **THEN** it SHALL match the response by id=1

#### Scenario: Notification has no id
- **WHEN** MCPClient sends an `initialized` notification
- **THEN** the message SHALL NOT contain an id field
