## Why

Phase 1 的前两个模块（llm-adapter、tool-system）已完成，但还没有能把它们串起来的运行时循环。需要一个 Agent Loop 来驱动 ReAct 模式：LLM 决策 → 工具执行 → 结果回传 → LLM 继续，直到任务完成或触发退出条件。这是 Phase 1 "最小可运行 Agent" 的核心。

## What Changes

- 新增 `AgentState` dataclass：持有 messages、tools、adapter、orchestrator、tool_context 等全部运行时依赖
- 新增 `ExitReason` 枚举：COMPLETED / MAX_TURNS / ABORT / ERROR
- 新增 `agent_loop(state) -> ExitReason`：ReAct 主循环，含 abort 检查、LLM 调用、工具 dispatch、轮次限制
- 新增消息格式 helper 函数：format_assistant_msg / format_tool_msg / format_user_msg
- 预留 Phase 3 compact 钩子位置（注释占位，不实现）

## Capabilities

### New Capabilities
- `agent-loop`: Agent 运行时循环 — AgentState 结构、ReAct 循环控制流、退出条件、消息格式转换

### Modified Capabilities

（无。llm-adapter 和 tool-system 的 spec 不需要修改，agent-loop 是它们的消费者。）

## Impact

- 新增 `src/agent/state.py` 和 `src/agent/loop.py`
- 依赖 `src/llm/adapter.py`（LLMAdapter、LLMResponse、ToolCallRequest）
- 依赖 `src/tools/base.py`（ToolContext、ToolResult）
- 依赖 `src/tools/registry.py`（ToolRegistry）
- 依赖 `src/tools/orchestrator.py`（ToolOrchestrator）
- 新增验证脚本 `scripts/test_agent_loop.py`
