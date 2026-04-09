## Context

Agent 工具调用目前无拦截机制。ToolOrchestrator 直接执行 tool.call()，没有权限检查、审计或自定义校验。Phase 5.2 Permission 需要 PreToolUse 拦截点，Phase 6 Telemetry 需要 PostToolUse 采集点。

CC 的 Hooks 系统有 28 种事件、6 种执行器、7000+ 行代码，为商业桌面客户端和企业插件生态设计。我们需要一个精简版：9 种事件、2 种执行器，核心约 200 行。

当前 orchestrator 流程：`cast_params → validate_params → tool.call() → return ToolResult`。

## Goals / Non-Goals

**Goals:**
- 9 种 Hook 事件覆盖工具、子Agent、管线、会话生命周期
- command + prompt 两种执行器，子进程 JSON 协议 + LLM 评估
- HookRunner 可注入 ToolOrchestrator，无 hooks 时零开销
- 配置从 settings.yaml（全局）+ agent frontmatter（角色级）加载
- Permission 模块（Phase 5.2）可作为 PreToolUse hook 注册

**Non-Goals:**
- HTTP hook 执行器（无外部 webhook 消费者）
- Agent hook 执行器（prompt hook 已够用）
- 多层配置优先级（CC 的 policy/project/user/session/plugin/skill 6 层）
- 文件监视（CC 的 FileChanged/CwdChanged）
- 交互式权限询问（CC 的 ask/passthrough，我们没有 UI）
- SessionStart/SessionEnd 集成点（类型先定义，Phase 6 接入）

## Decisions

### 1. Permission 作为 PreToolUse hook 而非独立管线

**选择**：Permission 模块注册为 PreToolUse hook，由 HookRunner 统一调度。
**替代方案**：Permission 和 Hooks 并列串联（原计划 `permission.check → hooks.pre → tool.call → hooks.post`）。
**理由**：统一入口，减少 orchestrator 的改动量。Permission 模块只需实现判断逻辑 + 注册自己，不需要知道 orchestrator 的存在。后续加限流、审计等也只需注册新 hook。

### 2. HookRunner 注入 ToolOrchestrator

**选择**：ToolOrchestrator 构造函数新增 `hook_runner: HookRunner | None = None`。
**理由**：向后兼容——不传 hook_runner 时行为不变。create_agent 工厂在构建 orchestrator 时注入 hook_runner。

### 3. Hook 执行模型

**选择**：所有匹配的 hooks 并行执行（asyncio.gather），每个 hook 独立超时。
**替代方案**：顺序执行。
**理由**：多个 hooks 之间通常无依赖（一个检查权限，一个做审计），并行更快。CC 也是并行执行。

### 4. Command hook 协议

**选择**：stdin 写 JSON（HookEvent payload），stdout 读 JSON（HookResult），退出码语义：0=allow, 2=deny, 其他=非阻塞错误。
**理由**：与 CC 完全一致，语言无关，调试方便（用 jq 就能手动测试）。

### 5. 结果聚合策略

**选择**：deny 优先（任一 deny 即阻断），modify 取最后一个，additional_context 拼接。
**替代方案**：第一个 deny 即短路。
**理由**：并行执行时无法保证顺序，所以必须等所有 hooks 完成后聚合。"deny 优先"是安全的默认策略。

### 6. 配置两层：settings.yaml + agent frontmatter

**选择**：全局 hooks 从 settings.yaml 的 `hooks` 节加载，角色级 hooks 从 agent .md frontmatter 的 `hooks` 字段加载。create_agent 时合并两层。
**替代方案**：CC 的 6 层优先级系统。
**理由**：我们是单部署服务端引擎，不需要 user/project/policy 层分离。Agent frontmatter hooks 比 CC 更直觉——在角色定义里直接声明安全策略。

### 7. Orchestrator 集成位置

改 `_execute_one` 方法，在 `tool.call()` 前后插入 hook 调用：

```
_execute_one(tc, tool, context):
    cast_params → validate_params
    ↓
    PreToolUse hooks → deny? → return error ToolResult
                     → modify? → 替换 params
                     → allow? → 继续
    ↓
    tool.call(params, context)
    ↓
    成功 → PostToolUse hooks → 追加 additional_context
    失败 → PostToolUseFailure hooks → 记录
    ↓
    return ToolResult
```

### 8. 生命周期事件集成

- SubagentStart/End：在 `spawn_agent.py` 的 `call()` 和后台协程完成回调中触发
- PipelineStart/End：在 `pipeline.py` 的 `execute_pipeline` 入口和出口触发
- SessionStart/End：先定义类型，Phase 6 API 层接入时补集成点

HookRunner 实例通过 ToolContext 传递（新增 `hook_runner` 字段），生命周期事件的触发点直接调用 `hook_runner.run(event)`。

## Risks / Trade-offs

- **Command hook 安全风险** → 用户配置的命令以服务进程权限运行。Mitigation：这是用户自己配置的，与 CC 同等信任模型。
- **Prompt hook 延迟** → 每次工具调用前多一次 LLM 调用。Mitigation：prompt hook 用 light tier，延迟 ~200ms；且通常只配在高风险工具上。
- **并行 hooks 中一个挂起** → 一个慢 hook 不影响其他 hooks，但整体等待会延迟工具执行。Mitigation：per-hook timeout，默认 30s。
- **SessionStart/End 无集成点** → Phase 5.1 只定义类型不接入。Risk：类型可能在 Phase 6 需要调整。Mitigation：这两个事件的 payload 很简单（session_id + project_id），调整成本低。
