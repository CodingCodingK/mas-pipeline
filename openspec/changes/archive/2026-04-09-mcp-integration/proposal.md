## Why

当前工具系统只有硬编码的内置工具（7 个），每增加一个外部工具都需要写 Python Tool class 并修改 `__init__.py`。MCP (Model Context Protocol) 是 Anthropic 推出的开放协议，定义了 LLM 与外部工具/资源的标准化通信。接入 MCP 后，只需在 settings.yaml 配置一个 server 即可获得该 server 暴露的所有工具，无需写代码。

## What Changes

- 新增 MCP client 模块：JSON-RPC 2.0 协议实现，支持 stdio 和 HTTP 两种传输
- 新增 MCPTool 适配器：将 MCP server 的工具包装为内置 Tool 接口，注册到 ToolRegistry
- 新增 MCPManager：Pipeline 级别的 MCP server 连接生命周期管理（启动/共享/清理）
- 新增 settings.yaml `mcp_servers` 配置段和 `mcp_default_access` 参数
- 修改 agent factory：加载 MCP 工具并注册到 per-agent ToolRegistry
- 修改 pipeline engine：创建 MCPManager 并传递给各 agent
- MCP 工具使用三段式命名 `mcp__serverName__toolName`，与内置工具共享 Orchestrator dispatch / Hooks / Permission 全路径
- 只实现 MCP Tools 能力，不做 Resources / Prompts / Sampling / Roots

## Capabilities

### New Capabilities

- `mcp-client`: MCP 协议客户端 — JSON-RPC 2.0 通信、stdio/HTTP 传输、initialize 握手、tools/list 发现、tools/call 调用
- `mcp-tool-adapter`: MCPTool 适配器 — 将 MCP server 工具包装为 Tool 接口、三段式命名、input_schema 透传
- `mcp-manager`: MCP 连接生命周期管理 — Pipeline 级共享连接池、按需启动、统一清理

### Modified Capabilities

- `agent-factory`: create_agent 接收 MCP 工具列表、按 role frontmatter `mcp_servers` 过滤、注册到 ToolRegistry
- `pipeline-execution`: execute_pipeline 创建 MCPManager、传递给各节点 agent、pipeline 结束时清理

## Impact

- 新增模块: `src/mcp/` (client, transport, tool, manager)
- 修改: `src/agent/factory.py`, `src/engine/pipeline.py`, `src/project/config.py`
- 新增依赖: 无（JSON-RPC 自己实现，stdio 用 asyncio.subprocess，HTTP 用已有的 httpx）
- 配置: `config/settings.yaml` 新增 `mcp_servers` 和 `mcp_default_access` 字段
