## Context

当前工具系统 (`src/tools/`) 只支持 Python 内置工具，通过 `get_all_tools()` 硬编码返回 7 个 Tool 实例。扩展工具需要写代码。MCP 协议提供标准化的 JSON-RPC 2.0 接口，允许 LLM 调用任意外部 server 暴露的工具。

现有代码：
- `src/tools/base.py` — Tool ABC, ToolResult, ToolContext
- `src/tools/registry.py` — ToolRegistry: register, get, list_definitions
- `src/tools/orchestrator.py` — dispatch with hooks/permission integration
- `src/agent/factory.py` — create_agent 构建 per-agent ToolRegistry
- `src/engine/pipeline.py` — execute_pipeline 调度多 agent
- `src/project/config.py` — Settings dataclass, get_settings()

## Goals / Non-Goals

**Goals:**
- MCP JSON-RPC 2.0 client：initialize 握手 + tools/list 发现 + tools/call 调用
- stdio 传输：spawn 子进程，stdin/stdout 通信
- HTTP 传输：SSE/Streamable HTTP 远程 server
- MCPTool 适配器：MCP 工具包装为 Tool 子类，三段式命名 `mcp__server__tool`
- MCPManager：Pipeline 级共享连接池，按需启动，统一清理
- Factory 集成：加载 MCP 工具，按 role frontmatter 过滤，注册到 ToolRegistry
- Pipeline 集成：创建 MCPManager，传递给 agent，pipeline 结束清理
- settings.yaml 配置：mcp_servers dict + mcp_default_access (all/none)

**Non-Goals:**
- MCP Resources / Prompts / Sampling / Roots（只做 Tools）
- MCP server 端实现（我们只做 client）
- 自动重连 / 健康检查（Phase 5 不做，失败直接报错）
- MCP server 认证 OAuth/XAA（简单 env 变量透传即可）

## Decisions

### D1: JSON-RPC 2.0 自己实现 vs 用库

自己实现。JSON-RPC 2.0 核心就是 `{jsonrpc: "2.0", method, params, id}` 请求 + `{jsonrpc: "2.0", result/error, id}` 响应，~50 行代码。不引入 `mcp` Python SDK（依赖重，且我们只用 Tools 子集）。

### D2: Transport 抽象

```python
class MCPTransport(ABC):
    async def start(self) -> None: ...
    async def send(self, message: dict) -> dict: ...
    async def close(self) -> None: ...

class StdioTransport(MCPTransport):
    """Spawn subprocess, communicate via stdin/stdout line-delimited JSON."""

class HTTPTransport(MCPTransport):
    """POST JSON-RPC to HTTP endpoint, SSE for server-initiated messages."""
```

两种传输共用同一个 MCPClient，只是底层 pipe 不同。

### D3: MCPClient 协议流程

```
Client                          Server
  │                               │
  │── initialize ───────────────▶ │  (协议版本, 能力声明)
  │◀── initialize response ───── │  (server 能力)
  │── initialized notification ─▶ │  (握手完成)
  │                               │
  │── tools/list ───────────────▶ │  (发现工具)
  │◀── tools list ──────────────  │  (工具名 + schema)
  │                               │
  │── tools/call ───────────────▶ │  (调用工具)
  │◀── tool result ─────────────  │  (执行结果)
  │                               │
  │── shutdown ─────────────────▶ │  (关闭)
  │◀── shutdown response ───────  │
  │── exit notification ────────▶ │
```

### D4: MCPTool 适配器

```python
class MCPTool(Tool):
    name = "mcp__github__create_issue"  # 三段式
    description = "..."                  # 来自 MCP server
    input_schema = {...}                 # 来自 MCP server inputSchema

    def __init__(self, server_name, tool_info, client):
        self._server_name = server_name
        self._original_name = tool_info["name"]  # 还原用
        self._client = client

    async def call(self, params, context) -> ToolResult:
        result = await self._client.call_tool(self._original_name, params)
        return ToolResult(output=result, success=True)
```

MCPTool 注册到 ToolRegistry 后，Orchestrator / Hooks / Permission 全透明。

### D5: MCPManager 生命周期

```python
class MCPManager:
    """Pipeline-level MCP connection pool."""

    async def start(self, server_configs: dict) -> None:
        """Connect to all configured servers concurrently."""

    def get_tools(self, server_names: list[str] | None = None) -> list[MCPTool]:
        """Get tools, optionally filtered by server names."""

    async def shutdown(self) -> None:
        """Close all server connections."""
```

- Pipeline 开始时 `start()`，结束时 `shutdown()`
- Factory 调 `get_tools()` 获取 MCPTool 列表注册到 per-agent registry
- MCPManager 持有 MCPClient 实例，不暴露底层连接

### D6: Factory 集成逻辑

```python
# In create_agent():
# 1. 从 role frontmatter 读 mcp_servers 字段
mcp_server_names = metadata.get("mcp_servers", None)

# 2. 如果 MCPManager 可用 (pipeline 传入)
if mcp_manager:
    if mcp_server_names is not None:
        # role 显式指定 → 只拿这些 server 的工具
        mcp_tools = mcp_manager.get_tools(mcp_server_names)
    elif mcp_default_access == "all":
        # 未指定 + 默认 all → 拿全部
        mcp_tools = mcp_manager.get_tools()
    else:
        # 未指定 + 默认 none → 不拿
        mcp_tools = []

    for tool in mcp_tools:
        registry.register(tool)
```

### D7: Pipeline 集成逻辑

```python
# In execute_pipeline():
mcp_manager = MCPManager()
try:
    settings = get_settings()
    if settings.mcp_servers:
        await mcp_manager.start(settings.mcp_servers)

    # ... execute nodes, pass mcp_manager to create_agent ...

finally:
    await mcp_manager.shutdown()
```

## Risks / Trade-offs

- **[Risk] MCP server 启动慢** → 并发启动所有 server（`asyncio.gather`），不串行
- **[Risk] MCP server 崩溃 mid-pipeline** → MCPTool.call 捕获异常返回 ToolResult(success=False)，不影响其他工具
- **[Risk] stdio server 进程泄漏** → MCPManager.shutdown 强制 kill，加 `__del__` 兜底
- **[Trade-off] 不做自动重连** → 简单，失败就是失败，用户重跑 pipeline。后续可加
- **[Trade-off] 不用 mcp Python SDK** → 少依赖，但需要自己处理协议细节（~200 行）
