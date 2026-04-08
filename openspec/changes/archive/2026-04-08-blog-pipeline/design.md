## Context

Pipeline Engine（execute_pipeline）已支持 YAML 驱动的 reactive 调度，Coordinator（run_coordinator）已支持路由分发。目前缺真实管线和外部检索工具。test_linear.yaml 三个节点全用 general 角色，无领域 prompt，无外部数据源。

现有工具池：read_file、shell、spawn_agent。无结构化的 web 搜索能力。

## Goals / Non-Goals

**Goals:**
- 实现 WebSearchTool，通过 Tavily API 提供结构化网页搜索
- 定义 blog_generation 管线 YAML（researcher → writer → reviewer）
- 编写三个专用角色 prompt，控制各节点输出质量
- 端到端验证：一句话输入 → 完整博客文章输出

**Non-Goals:**
- 不做 MCP client（Phase 5）
- 不做文件注入（上传文档作为输入，留到 Phase 4 courseware-pipeline）
- 不改 Pipeline Engine / Coordinator / create_agent 等现有代码逻辑
- 不做结构化输出解析（title/body/tags，Phase 6 API 层做）
- 不做 WebFetchTool（抓取指定 URL，后续按需加）

## Decisions

### D1: WebSearchTool 用 Tavily Search API

调用 `POST https://api.tavily.com/search`，返回结构化结果。

```python
class WebSearchTool(Tool):
    name = "web_search"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {"type": "integer", "description": "最大结果数", "default": 5}
        },
        "required": ["query"]
    }
```

ToolResult.output 格式：每条结果一个 block，包含 title、url、content snippet。LLM 可直接阅读。

**为什么不用 DuckDuckGo 爬取**：不稳定，易被限流。Tavily 专为 AI Agent 设计，免费 1000 次/月。
**为什么不用 CC 的 WebSearch 方式**：CC 依赖 Anthropic API 内置 `web_search_20250305` server tool，我们走 OpenAI-compatible 协议无此能力。

### D2: Tavily 配置走 settings.yaml

```yaml
tavily:
  api_key: ${TAVILY_API_KEY}
```

通过现有的 config 系统加载（env var 替换），与 providers 配置风格一致。

### D3: 管线拓扑 — 3 节点线性

```yaml
pipeline: blog_generation
description: 博客内容生产管线

nodes:
  - name: researcher
    role: researcher
    output: research

  - name: writer
    role: writer
    input: [research]
    output: draft

  - name: reviewer
    role: reviewer
    input: [draft]
    output: final_post
```

与 test_linear.yaml 同构，但每个节点用专用角色文件。依赖从 input/output 自动推导（Pipeline Engine 已支持）。

### D4: 角色文件设计

| 角色 | model_tier | tools | 核心职责 |
|------|-----------|-------|---------|
| researcher | medium | [web_search, read_file] | 搜索 + 整理调研报告 |
| writer | medium | [read_file] | 根据调研写博客草稿 |
| reviewer | medium | [] | 纯文本审校润色，输出终稿 |

**为什么 reviewer 无工具**：审校是纯文本操作，给工具反而分散注意力。
**为什么都用 medium tier**：博客质量要求不低，light tier 质量不够。heavy tier 成本高，medium 是平衡点。

### D5: WebSearchTool 的并发安全与只读性

web_search 是只读的（不修改任何状态），也是并发安全的（每次调用独立 HTTP 请求）。

```python
def is_concurrency_safe(self, params): return True
def is_read_only(self, params): return True
```

这让 ToolOrchestrator 可以并行调度多个搜索请求。

## Risks / Trade-offs

**[Tavily 免费额度]** → 1000 次/月。开发测试够用，生产需要付费或换引擎。后续 Phase 5 MCP 接入时可替换为任意搜索 MCP server。

**[搜索结果质量]** → Tavily 返回的 content snippet 可能不够详细。researcher prompt 中引导 LLM 综合多条结果，而非依赖单条。

**[角色 prompt 调优]** → 首版 prompt 不一定最优。这是迭代的事，先跑通再调。

**[无 WebFetch]** → researcher 能搜到 URL 但不能深入抓取页面全文。Phase 2.9 先不做，如需后续加 WebFetchTool。
