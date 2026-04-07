## Context

Phase 0 已完成基础设施，Phase 1.1 llm-adapter 已完成 LLM 调用层。LLM 返回的 `ToolCallRequest(id, name, arguments)` 需要一个执行层来处理。本模块是 Phase 1.3 agent-loop 的前置依赖。

已有接口约定：
- `LLMAdapter.call(messages, tools: list[dict])` — tools 参数为 OpenAI function calling 格式
- `LLMResponse.tool_calls: list[ToolCallRequest]` — LLM 返回的工具调用请求

参考了 Claude Code 的 BashTool / toolOrchestration 实现，在复杂度和功能之间取平衡。

## Goals / Non-Goals

**Goals:**
- 提供 Tool 抽象基类，支持内置工具和未来外接工具（MCP/Skill）统一注册
- 参数校验容错：LLM 常见类型偏差（"123" vs 123）自动修正，减少无谓重试
- 调度层根据工具并发安全性自动分批，safe 并发 / unsafe 串行
- 两个内置工具验证完整链路：read_file + shell

**Non-Goals:**
- 权限系统（Phase 5）— `is_read_only` 保留接口但不消费
- MCP / Skill 外接工具（Phase 5）— Registry 支持动态注入但本阶段不实现
- 流式工具执行（Phase 5 Streaming）
- 沙盒隔离（不做）

## Decisions

### D1: 安全属性命名 — `is_concurrency_safe` 而非 `is_safe`

`is_safe` 歧义太大（安全？无副作用？可回滚？）。`is_concurrency_safe(params)` 语义精确：调度层能否将此工具与其他工具并发执行。

`is_read_only(params)` 保留接口，Phase 1 默认等价于 `is_concurrency_safe`，Phase 5 权限系统消费。

两个方法都接收 `params: dict`，支持动态判断（如 shell 根据命令内容决定）。

**替代方案**：单个 `safe: bool` 属性 → 无法区分并发安全和权限只读两个维度，Phase 5 需要重构。

### D2: shell 动态安全判断 — 白名单前缀 + 复合命令拆分（~30 行）

参考 CC 的 BashTool（2000 行 readOnlyValidation.ts），取其核心思路，砍掉不需要的部分：

| 保留 | 原因 |
|------|------|
| 白名单前缀匹配 | 基础能力，SAFE_PREFIXES 列表 |
| 复合命令拆分逐段检查 | `&&` `\|\|` `;` `\|` 拆子命令，每段过白名单 |
| 变量展开检测 | 含 `$` 或反引号 → unsafe |
| 重定向检测 | 含 `>` → unsafe |

| 不做 | 原因 |
|------|------|
| 逐 flag 校验 | CC 维护每个命令的安全 flag 字典，2000 行，投入产出比不够 |
| Git bare repo / hooks 注入防御 | 沙盒逃逸场景，我们没沙盒 |
| Windows UNC 路径防御 | 极端边界 |
| 引号内 glob 展开分析 | 复杂度高，收益低 |

**替代方案**：全部硬编码 unsafe → 所有 shell 命令串行，性能差但零风险。选择动态判断是因为 Agent 大量使用 `git log`、`ls`、`cat` 等只读命令，串行会显著拖慢。

### D3: 返回值 — `ToolResult` dataclass 而非纯 str

```python
@dataclass
class ToolResult:
    output: str           # 给 LLM 看的文本
    success: bool = True  # 给 telemetry / 调度层用
    metadata: dict = {}   # exit_code, file_size 等，不进 LLM context
```

CC 的 `ToolResult<T>` 还有 `newMessages`（注入额外对话消息）、`contextModifier`（运行时配置热切换）、`mcpMeta`（MCP 透传）。我们不需要：
- `newMessages` — CC 用于 FileReadTool 读多模态内容，Phase 4 才需要
- `contextModifier` — CC 用于 SkillTool 热切换模型/工具白名单，我们的 subAgent 在创建时就确定配置
- `mcpMeta` — Phase 5 MCP 才需要

以上字段未来需要时直接加，纯增量不破坏。

**替代方案**：返回纯 str → `telemetry_events.tool_success` 字段无法准确记录，只能靠 try/catch。

### D4: 参数处理 — cast → validate → call

LLM 经常犯类型错误（数字传成字符串、布尔传成 "true"）。

`cast_params` 根据 JSON Schema type 声明做安全转换（str→int/float/bool, float→int, str→list），转不了原样保留。`validate_params` 走 JSON Schema 校验，失败格式化错误返回 LLM 重试（不抛异常）。

**替代方案**：直接 validate 不 cast → LLM 每次类型偏差都浪费一轮调用。~40 行 cast 代码换来显著减少无谓重试。

### D5: 注册方式 — 手动注册

CC 40+ 工具也是手动 import + 列举（`src/tools.ts` 的 `getAllBaseTools()`），无自动扫描。Phase 1 只有 2 个工具，手动注册最简单。MCP/Skill 通过同一个 `register()` 接口动态注入。

### D6: shell 工作目录 — 实例维护 _cwd，cd 跨调用持久化

参考 CC：每次命令执行后追加 `pwd` 读回当前目录，使 `cd` 效果跨调用持久化。Phase 1 单 Agent 用实例属性即可，Phase 2 多 Agent 时通过 ToolContext 做 per-agent 隔离。

## Risks / Trade-offs

- **[白名单不全]** → shell 的 SAFE_PREFIXES 可能遗漏常用只读命令 → 只影响并发性能，不影响正确性，发现后加即可
- **[cast 过度转换]** → 极端情况下 cast 可能把 LLM 有意传的字符串转成数字 → 概率极低，JSON Schema 有明确类型声明，cast 严格按声明转换
- **[shell 超时]** → 默认 120s，长时间命令会被 kill → 可通过 ToolContext 或参数覆盖
- **[输出截断]** → 30000 字符截断可能丢失关键尾部输出 → 截断时在末尾标注 "[truncated]"，LLM 可重新请求
