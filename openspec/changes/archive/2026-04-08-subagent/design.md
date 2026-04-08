## Context

Phase 1 已有：AgentState / agent_loop / ToolRegistry / ToolOrchestrator / ToolContext / context builder / router。Phase 2.4 已有 Task manager（create/claim/complete/fail/list/get/check_blocked）。`pipeline_runs` 表已在 Phase 0 init_db.sql 建好，但无 ORM model。

## Goals / Non-Goals

**Goals:**
- Agent 工厂：从 role 文件一键创建独立 AgentState
- spawn_agent 工具：异步后台启动子 Agent，自动创建 Task 跟踪
- Task 工具集：LLM 可用的 task_create / task_update / task_list / task_get
- Task 与 spawn 解耦：LLM 可以只规划不执行，也可以直接 spawn 不预规划
- 全局工具池：所有内置工具集中管理，Agent 按白名单过滤

**Non-Goals:**
- 不做系统级 DAG 强制调度（2.7 Pipeline Engine 的事）
- 不做子 Agent 嵌套 spawn（子 Agent 禁用 spawn_agent）
- 不做 Agent 间通信（Phase 5 SendMessage）
- 不做完成通知推送（Phase 5 event-bus，当前 LLM 主动轮询）
- 不做 Pipeline Run 完整管理（2.6 补全）

## Decisions

### D1. Task 与 spawn 解耦（参考 CC TaskCreate 与 AgentTool 独立设计）

Task 是 LLM 的规划清单，spawn_agent 是执行工具，无系统级绑定。spawn_agent 内部自动创建一条 Task 跟踪子 Agent 状态，但 LLM 也可以单独 task_create 做规划而不 spawn。blocked_by 是给 LLM 参考的依赖信息，不做系统级强制检查。

### D2. spawn_agent 异步后台执行

spawn_agent 调用后立即返回 task_id，子 Agent 通过 `asyncio.create_task` 后台执行。完成后自动调 complete_task(task_id, result) 或 fail_task(task_id, error)。父 Agent 用 task_list / task_get 轮询状态和取结果。

### D3. 全局工具池 + 子 Agent 禁用列表（参考 CC getAllBaseTools + ALL_AGENT_DISALLOWED_TOOLS）

`get_all_tools()` 返回所有内置工具实例的字典。`AGENT_DISALLOWED_TOOLS` 列出子 Agent 不可用的工具（spawn_agent）。create_agent 从全局池按白名单过滤，再排除禁用列表。

### D4. task_description 作为 user message（参考 CC AgentTool createUserMessage）

task_description 通过 `build_messages(user_input=task_description)` 注入为子 Agent 的第一条 user message，不放 system prompt。

### D5. 子 Agent 输出提取（参考 CC finalizeAgentTool）

从 state.messages 倒序查找最后一条 role=assistant 且有 content（非空字符串）的消息。如果最后一条 assistant 只有 tool_calls 没有 text，继续向前回溯。异常退出（MAX_TURNS/ERROR/ABORT）在结果前加前缀说明退出原因。

### D6. abort_signal 共享

子 Agent 共享父 Agent 的 asyncio.Event 实例。父取消时子同时退出。

### D7. Task 工具 run_id 自动注入

所有 Task 工具从 ToolContext.run_id 自动获取 run_id，LLM 参数中不暴露 run_id。

## Risks / Trade-offs

- **[LLM 轮询效率]** → 子 Agent 完成后无主动通知，LLM 需要自己判断何时 task_list 查看。可能多耗几轮对话。Phase 5 event-bus 可改为推送通知
- **[run_id 前置]** → Pipeline Run 完整管理在 2.6，2.5 只写最小 create_run。PipelineRun model 字段可能在 2.6 调整
- **[单事件循环并发]** → 多个子 Agent 在同一个 asyncio 事件循环里并发执行。LLM API 调用是 IO-bound，并发没问题。但如果子 Agent 的工具有 CPU-bound 操作（如大文件处理），可能阻塞。Phase 2 可接受
