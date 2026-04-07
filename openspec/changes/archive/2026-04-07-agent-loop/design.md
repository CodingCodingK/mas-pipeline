## Context

Phase 1.1（llm-adapter）和 Phase 1.2（tool-system）已完成，提供了 LLM 调用和工具执行能力。现在需要一个运行时循环将两者串联：接收用户输入 → LLM 决策 → 工具执行 → 结果回传 → LLM 继续，直到完成或触发退出条件。

现有依赖：
- `LLMAdapter.call(messages, tools, **kwargs) -> LLMResponse`
- `ToolOrchestrator.dispatch(tool_calls, context) -> list[ToolResult]`
- `ToolRegistry.list_definitions(names?) -> list[dict]`
- `ToolContext(agent_id, run_id, project_id, abort_signal)`

参考 CC 的 `query()` 函数（query.ts）和 `State` 类型，简化适配。

## Goals / Non-Goals

**Goals:**
- 实现 ReAct 循环：LLM → tool call → result → LLM → ... → 最终回复
- AgentState 持有全部运行时依赖，支持后续 Phase 增量扩展
- 明确的退出条件枚举，覆盖正常完成、轮次上限、中断、错误
- 消息格式直接用 OpenAI dict，零转换成本
- 预留 Phase 3 compact 钩子位置

**Non-Goals:**
- 不实现 compact（Phase 3）
- 不实现 telemetry 采集（Phase 6）
- 不实现流式输出（Phase 5）
- 不实现 context-builder（Phase 1.4 单独做）
- 不实现 hooks/permissions 集成（Phase 5）

## Decisions

### D1: AgentState 结构 — 所有依赖放进 dataclass

**选择：** 方案 A — adapter、tools、orchestrator、tool_context 全部作为 AgentState 字段。

**替代方案：** 方案 B — 依赖外传给 agent_loop 函数参数（CC 的 QueryParams 模式）。

**理由：** Python mutable dataclass 天然支持运行时改字段，Phase 5 Skill inline 模式如需改模型/权限直接 `state.adapter = new_adapter`，不需要 CC 的 contextModifier 模式。全 7 Phase 扫描确认可行。CC 的 State 也把 toolUseContext 放在内部（query.ts:206）。

### D2: ToolContext 归属 — 轻量对象住在 AgentState 内

**选择：** `state.tool_context` 持有 agent_id、run_id、project_id、abort_signal。AgentState 不再重复这些字段。

**替代方案：** AgentState 平铺 agent_id/run_id/project_id + 每轮新建 ToolContext。

**理由：** 消除字段重复。ToolContext 生命周期与 Agent 相同，不需要每轮重建。Phase 5 的 Hooks/Permissions 放在 Orchestrator 而非 ToolContext，保持 ToolContext 轻量。

### D3: 退出条件 — str Enum，Phase 1 四个值

**选择：** `ExitReason(str, Enum)` — COMPLETED、MAX_TURNS、ABORT、ERROR。

**替代方案：** 纯字符串（CC 模式）；LoopResult 包装类。

**理由：** str+Enum 兼顾序列化和类型检查。CC 的 aborted_streaming/aborted_tools 合并为 ABORT（Phase 1 无流式）。返回值不包装 LoopResult，上层需要 turn_count 从 state 直接读。Phase 3 加 TOKEN_LIMIT，Phase 5 加 HOOK_STOPPED。

### D4: 消息格式 — OpenAI dict

**选择：** `state.messages: list[dict]`，直接用 OpenAI chat completion 格式。

**替代方案：** 自定义 Message dataclass 体系（CC 的 13 种 MessageType）。

**理由：** 零转换成本发 API；dict 直接 JSON 序列化到 Redis/PG；compact 直接操作 dict。Phase 4 Anthropic 转换只在 adapter 内部做。用 helper 函数（format_assistant_msg 等）保证构造正确性。arguments 内存存 dict 方便读取，发 API 时 json.dumps。thinking 存为非标准字段。

### D5: abort 检查 — 两个检查点

**选择：** 调 LLM 前检查一次，工具执行后检查一次。

**理由：** 工具执行中的中断由 ToolContext.abort_signal 传递给各工具自行处理。两个点覆盖了 loop 的两个主要阻塞阶段。

### D6: LLM 错误处理 — loop 层直接 return ERROR

**选择：** adapter 层已做 429/5xx 重试（3 次），到 loop 层的异常都是不可恢复错误，直接 return ERROR。

**替代方案：** loop 层再加重试逻辑。

**理由：** 重试职责清晰分层，不重复。

## Risks / Trade-offs

- **[AgentState 字段膨胀]** → Phase 5 预计 12-15 个字段，仍可接受。如果到不舒服的程度，再拆 identity/runtime 子对象。
- **[dict 无类型检查]** → helper 函数保证构造正确，运行时 LLM API 会报格式错误。可接受的 trade-off。
- **[compact 只是注释占位]** → Phase 3 前长对话会撑爆 context window。Phase 1 验证场景对话短，不是问题。
