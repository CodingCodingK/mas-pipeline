## Why

Pipeline Engine 和 Coordinator 已就绪，但目前只有测试用的骨架管线（test_linear.yaml 全用 general 角色）。需要第一条有业务意义的端到端管线来验证整个系统：专用角色 prompt → 真实外部检索 → 多节点协作产出完整博客。同时补齐缺失的 web_search 工具，让 Agent 具备外部信息获取能力。

## What Changes

- 新增 `pipelines/blog_generation.yaml` — 3 节点线性管线（researcher → writer → reviewer）
- 新增 `agents/researcher.md` — 调研角色，tools: [web_search, read_file]
- 新增 `agents/writer.md` — 写作角色，tools: [read_file]
- 新增 `agents/reviewer.md` — 审校角色，tools: []
- 新增 `src/tools/builtins/web_search.py` — WebSearchTool，调用 Tavily Search API
- 注册 web_search 到全局工具池 `get_all_tools()`
- `config/settings.yaml` 新增 `tavily.api_key` 配置项

## Capabilities

### New Capabilities
- `web-search`: WebSearchTool 内置工具，通过 Tavily API 执行网页搜索，返回结构化结果（title/url/content）
- `blog-pipeline`: 博客生产管线定义（YAML）+ 三个专用角色文件（researcher/writer/reviewer）

### Modified Capabilities
- `tool-builtins`: 全局工具池新增 web_search 工具

## Impact

- 新增文件：1 个 YAML + 3 个角色 md + 1 个 tool py + 1 个验证脚本
- 修改文件：`src/tools/builtins/__init__.py`（注册 web_search）、`config/settings.yaml`（tavily 配置）
- 新增依赖：无（Tavily API 通过已有的 httpx 调用）
- 外部依赖：Tavily API key（免费 1000 次/月）
