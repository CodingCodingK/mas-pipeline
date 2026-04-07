## 1. AgentState 和 ExitReason

- [x] 1.1 创建 `src/agent/__init__.py`
- [x] 1.2 创建 `src/agent/state.py` — ExitReason(str, Enum) 枚举：COMPLETED / MAX_TURNS / ABORT / ERROR
- [x] 1.3 在 `src/agent/state.py` 中实现 AgentState dataclass：messages, tools, adapter, orchestrator, tool_context, turn_count, max_turns, has_attempted_reactive_compact

## 2. 消息格式 Helper 函数

- [x] 2.1 创建 `src/agent/messages.py` — format_assistant_msg(response: LLMResponse) -> dict：处理 content、tool_calls（arguments 存 dict）、thinking 字段
- [x] 2.2 实现 format_tool_msg(tool_call_id: str, result: ToolResult) -> dict
- [x] 2.3 实现 format_user_msg(text: str) -> dict

## 3. Agent Loop 主循环

- [x] 3.1 创建 `src/agent/loop.py` — agent_loop(state: AgentState) -> ExitReason 函数签名
- [x] 3.2 实现 abort 检查（调 LLM 前 + 工具执行后，两个检查点）
- [x] 3.3 实现 LLM 调用：state.adapter.call(state.messages, state.tools.list_definitions())
- [x] 3.4 实现异常捕获 → return ExitReason.ERROR
- [x] 3.5 实现 assistant message 追加 + 无 tool_calls 时 return COMPLETED
- [x] 3.6 实现工具 dispatch：state.orchestrator.dispatch(response.tool_calls, state.tool_context)
- [x] 3.7 实现 tool result messages 追加
- [x] 3.8 实现 turn_count 递增 + max_turns 检查 → return MAX_TURNS
- [x] 3.9 添加 compact 注释占位：microcompact/autocompact/blocking_limit（调 LLM 前）+ reactive compact（LLM 返回后）

## 4. 验证

- [x] 4.1 创建 `scripts/test_agent_loop.py` — 构造 AgentState，发送简单指令，验证 ReAct 循环：LLM → tool call → result → LLM → 最终回复
- [x] 4.2 验证退出条件：COMPLETED（无 tool_calls）、MAX_TURNS（设 max_turns=2 触发）
- [x] 4.3 验证消息格式：检查 state.messages 中各 dict 的 role/content/tool_calls/tool_call_id 格式正确
