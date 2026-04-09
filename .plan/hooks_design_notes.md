# Hooks 系统设计笔记

## CC Hooks 参考概况

- 28 种事件、6 种执行器（command/prompt/agent/http/callback/function）
- 主文件 `hooks.ts` 超 7000 行
- 6 层配置优先级：policySettings > projectSettings > userSettings > sessionHooks > pluginHooks > skillHooks
- 退出码协议：0=allow, 2=deny（blocking）, 其他=非阻塞错误
- 所有匹配 hooks 并行执行（asyncio.gather 等价）
- AsyncGenerator 流式返回进度 + 最终结果

## 我们的精简版

9 种事件、2 种执行器（command + prompt）、2 层配置（settings.yaml + agent frontmatter）。

### 事件清单

| 事件 | 集成点 | Phase 5.1 接通？ |
|------|--------|:---:|
| PreToolUse | orchestrator._execute_one（tool.call 前） | ✅ |
| PostToolUse | orchestrator._execute_one（tool.call 后，成功） | ✅ |
| PostToolUseFailure | orchestrator._execute_one（tool.call 后，失败） | ✅ |
| SubagentStart | spawn_agent.py call() | ✅ |
| SubagentEnd | spawn_agent.py 后台协程完成回调 | ✅ |
| PipelineStart | pipeline.py execute_pipeline 入口 | ✅ |
| PipelineEnd | pipeline.py execute_pipeline 出口 | ✅ |
| SessionStart | Phase 6 API 层 | ❌ 先定义类型 |
| SessionEnd | Phase 6 API 层 | ❌ 先定义类型 |

### 执行器

| 类型 | 机制 |
|------|------|
| command | subprocess, stdin 写 JSON, stdout 读 JSON, 退出码语义 |
| prompt | 调 route("light") LLM, $ARGUMENTS 替换为事件 JSON |

## 核心流程

### 当前流程（无 hooks）

```
orchestrator._execute_one(tc, tool, context)
    │
    ├─ cast_params(args, schema)
    ├─ validate_params(params, schema)
    │   └─ 失败 → return ToolResult(error)
    ├─ tool.call(params, context)
    │   └─ 异常 → return ToolResult(error)
    └─ return ToolResult(output)
```

### 新流程（hooks 集成后）

```
orchestrator._execute_one(tc, tool, context)
    │
    ├─ cast_params → validate_params
    │   └─ 失败 → return ToolResult(error)
    │
    ├─ 【PreToolUse hooks】
    │   ├─ 构造 HookEvent(PRE_TOOL_USE, {tool_name, tool_input, agent_id, run_id})
    │   ├─ hook_runner.run(event)
    │   │   ├─ matcher 过滤：按 tool_name 匹配
    │   │   ├─ 并行执行所有匹配的 hooks（asyncio.gather）
    │   │   └─ aggregate_results()
    │   └─ 结果判断：
    │       ├─ deny  → return ToolResult("Hook denied: {reason}", success=False)
    │       ├─ modify → params = updated_input
    │       └─ allow  → 继续
    │
    ├─ tool.call(params, context)
    │
    ├─ 成功？
    │   ├─ YES →【PostToolUse hooks】
    │   │   └─ 触发通知，additional_context 追加到 output
    │   └─ NO  →【PostToolUseFailure hooks】
    │       └─ 触发通知/日志
    │
    └─ return ToolResult
```

### 生命周期事件流程

```
spawn_agent.call():
    ├─ 创建 AgentRun 记录
    ├─ hook_runner.run(SubagentStart)     ← 新增
    ├─ asyncio.create_task(后台协程)
    └─ return agent_run_id

    后台协程完成:
        ├─ complete/fail agent_run
        ├─ push notification
        └─ hook_runner.run(SubagentEnd)   ← 新增

execute_pipeline():
    ├─ hook_runner.run(PipelineStart)     ← 新增
    ├─ update_run_status(RUNNING)
    ├─ ... 节点调度循环 ...
    ├─ finish_run()
    └─ hook_runner.run(PipelineEnd)       ← 新增
```

## HookResult 聚合策略

多个 hooks 并行返回后聚合：

```
results = [hook_a_result, hook_b_result, hook_c_result]

1. 有任一 deny → 最终 deny（安全优先）
2. 无 deny，有 modify → 最后一个 modify 的 updated_input 生效
3. additional_context：所有 hooks 的拼接（"\n" 连接）
```

## HookResult 与 CC 对比

| 字段 | CC | 我们 | 说明 |
|------|:---:|:---:|------|
| action (allow/deny/modify) | ✗ 散布在多字段 | ✅ 统一枚举 | CC 用 continue + decision + permissionDecision 三字段 |
| reason | ✅ | ✅ | deny 时的理由 |
| updated_input | ✅ | ✅ | modify 时替换参数 |
| additional_context | ✅ | ✅ | 追加给 LLM 的信息 |
| suppressOutput | ✅ | ✗ | 我们没有 transcript |
| updatedMCPToolOutput | ✅ | ✗ | MCP 后面再说 |
| watchPaths | ✅ | ✗ | 我们没有 file watcher |
| stopReason | ✅ | ✗ | deny + reason 已覆盖 |
| permissionDecision (ask/passthrough) | ✅ | ✗ | 交互式 UI，我们没有 |

## 配置结构

### settings.yaml（全局）

```yaml
hooks:
  pre_tool_use:
    - matcher: "shell"
      hooks:
        - type: command
          command: "python scripts/validate_shell.py"
          timeout: 10
    - matcher: "spawn_agent"
      hooks:
        - type: prompt
          prompt: "Is spawning this agent appropriate? $ARGUMENTS"
  post_tool_use:
    - hooks:
        - type: command
          command: "python scripts/audit_log.py"
```

### Agent frontmatter（角色级）

```yaml
# agents/researcher.md
---
name: researcher
model_tier: medium
tools: [read_file, search_docs]
hooks:
  pre_tool_use:
    - matcher: "shell"
      hooks:
        - type: command
          command: "exit 2"   # 直接 deny 所有 shell
---
```

### 合并规则

create_agent 时：全局 hooks + 角色 hooks 合并，都执行，角色 hooks 不覆盖全局。

## 关键设计决策

1. **Permission = PreToolUse hook**：不独立，注册为 hook，统一入口
2. **HookRunner 注入 Orchestrator**：`ToolOrchestrator(registry, hook_runner=None)`，无 hooks 时零开销
3. **并行执行 + per-hook 超时**：默认 30s，一个 hook 挂起不影响其他
4. **Command hook JSON 协议**：与 CC 一致，退出码 0/2/other，语言无关
5. **两层配置**：settings.yaml + agent frontmatter，不需要 CC 的 6 层
