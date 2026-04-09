## 1. JSON-RPC & Transport

- [x] 1.1 Create `src/mcp/__init__.py` module init
- [x] 1.2 Create `src/mcp/jsonrpc.py` — JSON-RPC 2.0 message builders: make_request(method, params, id), make_notification(method, params), parse_response(data)
- [x] 1.3 Create `src/mcp/transport.py` — MCPTransport ABC (start/send/close)
- [x] 1.4 Implement `StdioTransport` — asyncio.create_subprocess_exec, stdin/stdout line-delimited JSON, env merge with os.environ
- [x] 1.5 Implement `HTTPTransport` — httpx POST JSON-RPC, parse JSON response

## 2. MCP Client

- [x] 2.1 Create `src/mcp/client.py` — MCPClient class with transport reference
- [x] 2.2 Implement `initialize()` — send initialize request (protocol version + capabilities), receive response, send initialized notification
- [x] 2.3 Implement `list_tools()` — send tools/list, return list of tool defs (name, description, inputSchema)
- [x] 2.4 Implement `call_tool(name, arguments)` — send tools/call, return result content string, raise on isError
- [x] 2.5 Implement `shutdown()` — send shutdown request, send exit notification, close transport

## 3. MCPTool Adapter

- [x] 3.1 Create `src/mcp/tool.py` — MCPTool(Tool) class: three-part name, description, input_schema from server, call() forwards to MCPClient
- [x] 3.2 Implement `create_mcp_tools(server_name, client)` — list_tools + wrap each as MCPTool

## 4. MCPManager

- [x] 4.1 Create `src/mcp/manager.py` — MCPManager class
- [x] 4.2 Implement `start(server_configs)` — for each config: create transport (stdio/HTTP by config shape), create MCPClient, initialize, list_tools, store. Concurrent via asyncio.gather, failed servers logged and skipped
- [x] 4.3 Implement `get_tools(server_names=None)` — return MCPTool list, optionally filtered by server names
- [x] 4.4 Implement `shutdown()` — close all clients, log errors, don't raise
- [x] 4.5 Implement async context manager — `__aenter__` returns self, `__aexit__` calls shutdown

## 5. Config Integration

- [x] 5.1 Update `src/project/config.py` — add `mcp_servers: dict = {}` and `mcp_default_access: str = "all"` to Settings

## 6. Factory Integration

- [x] 6.1 Update `create_agent` signature — add optional `mcp_manager: MCPManager | None = None` parameter
- [x] 6.2 Implement MCP tool loading in create_agent — read role frontmatter `mcp_servers`, apply mcp_default_access logic, register MCPTool instances to ToolRegistry

## 7. Pipeline Integration

- [x] 7.1 Update `execute_pipeline` — create MCPManager, start from settings.mcp_servers, pass to _run_node/create_agent, shutdown in finally block

## 8. Tests

- [x] 8.1 Unit tests for jsonrpc: make_request, make_notification, parse_response (valid/error)
- [x] 8.2 Unit tests for StdioTransport: start/send/close (mock subprocess)
- [x] 8.3 Unit tests for HTTPTransport: start/send/close (mock httpx)
- [x] 8.4 Unit tests for MCPClient: initialize, list_tools, call_tool, shutdown (mock transport)
- [x] 8.5 Unit tests for MCPTool: name format, call forwarding, error handling
- [x] 8.6 Unit tests for create_mcp_tools: wraps all tools from client
- [x] 8.7 Unit tests for MCPManager: start (concurrent, failure isolation), get_tools (all/filtered), shutdown (error tolerance), context manager
- [x] 8.8 Unit tests for factory: create_agent with mcp_manager (all access / whitelist / none / no manager)
- [x] 8.9 Integration tests for pipeline: execute_pipeline with mock MCP servers, MCP lifecycle (start before nodes, shutdown after)

## 9. Docs

- [x] 9.1 Update `.plan/progress.md` — mark Phase 5.4 MCP complete
- [x] 9.2 Update `.plan/mcp_design_notes.md` — add implementation details
