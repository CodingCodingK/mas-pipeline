## 1. StreamEvent 基础设施

- [x] 1.1 创建 `src/streaming/__init__.py` 和 `src/streaming/events.py`，定义 StreamEvent dataclass（9 种事件类型）
- [x] 1.2 实现 `StreamEvent.to_sse() -> str` 方法，将 StreamEvent 序列化为 SSE 格式字符串（`event: {type}\ndata: {json}\n\n`）

## 2. LLMAdapter ABC 扩展

- [x] 2.1 在 `src/llm/adapter.py` 的 LLMAdapter ABC 中新增 `call_stream()` 抽象方法，签名 `async def call_stream(messages, tools=None, **kwargs) -> AsyncIterator[StreamEvent]`

## 3. OpenAICompatAdapter.call_stream()

- [x] 3.1 在 `src/llm/openai_compat.py` 实现 `call_stream()` — 发送 `stream=True` 请求，逐行解析 SSE，翻译 delta 为 StreamEvent 并 yield
- [x] 3.2 处理 text_delta、thinking_delta、tool_start/tool_delta/tool_end、usage、done 事件
- [x] 3.3 处理 retry（流开始前 429/5xx 重试）和 mid-stream error（yield error 事件）
- [x] 3.4 处理多 tool_call（多 index 并存）和空 content delta 跳过

## 4. AnthropicAdapter.call_stream()

- [x] 4.1 在 `src/llm/anthropic.py` 实现 `call_stream()` — 发送 `stream=True` 请求，解析 Anthropic SSE 事件（content_block_start/delta/stop、message_delta/stop）
- [x] 4.2 处理 text_delta、thinking_delta（含 beta header）、tool_start/tool_delta/tool_end
- [x] 4.3 处理 usage（从 message_start + message_delta 合并）和 done（stop_reason 映射）
- [x] 4.4 处理 retry 和 mid-stream error

## 5. agent_loop AsyncGenerator 改造

- [x] 5.1 AgentState 新增 `exit_reason: ExitReason | None = None` 字段
- [x] 5.2 将 `agent_loop` 从 `async def -> ExitReason` 改为 `AsyncGenerator[StreamEvent, None, None]`
- [x] 5.3 内部调用 `adapter.call_stream()` 并 yield 事件，同时累积 content/tool_calls 为完整 assistant message
- [x] 5.4 tool_end 后 dispatch 工具，yield StreamEvent(type="tool_result") 事件
- [x] 5.5 保持 compact 集成不变（micro/auto/reactive 在轮间执行）
- [x] 5.6 所有退出路径设置 `state.exit_reason` 而非 return ExitReason
- [x] 5.7 实现 `run_agent_to_completion(state) -> ExitReason` helper

## 6. 调用方适配

- [x] 6.1 `src/tools/builtins/spawn_agent.py` — 将 `await agent_loop(state)` 改为 `await run_agent_to_completion(state)`，从 `state.exit_reason` 读取结果
- [x] 6.2 `src/engine/pipeline.py` — 节点执行改用 `run_agent_to_completion`，从 `state.exit_reason` 判断成功/失败
- [x] 6.3 `src/engine/coordinator.py` — coordinator_loop 改为 AsyncGenerator[StreamEvent]，内部 `async for event in agent_loop(state): yield event`
- [x] 6.4 实现 `run_coordinator_to_completion(state) -> ExitReason` helper
- [x] 6.5 `run_coordinator` 路由函数适配新签名

## 7. 测试 — 单元测试

- [x] 7.1 StreamEvent 构造测试 — 9 种事件类型各构造一次，验证字段默认值
- [x] 7.2 StreamEvent.to_sse() 序列化测试 — 每种事件类型的 SSE 输出格式正确
- [x] 7.3 OpenAI call_stream mock 测试 — 模拟 SSE 行，验证 yield 出的 StreamEvent 序列正确
- [x] 7.4 OpenAI call_stream 多 tool_call 测试 — 模拟两个 tool_call（index 0 和 1），验证 tool_start/tool_delta/tool_end 各两组且按 index 排序
- [x] 7.5 OpenAI call_stream 空 content delta 跳过测试 — 模拟 delta.content="" 和 null，验证不 yield text_delta
- [x] 7.6 Anthropic call_stream mock 测试 — 模拟 Anthropic SSE 事件序列，验证 StreamEvent 序列正确
- [x] 7.7 Anthropic call_stream thinking block 测试 — 模拟 thinking content_block，验证 thinking_delta 事件和 beta header
- [x] 7.8 Anthropic call_stream stop_reason 映射测试 — tool_use → "tool_calls"，end_turn → "stop"
- [x] 7.9 call_stream retry 测试 — 模拟首次 429 + 第二次 200 成功，验证重试后正常流式
- [x] 7.10 call_stream mid-stream error 测试 — 模拟流中途断开，验证 yield error 事件

## 8. 测试 — agent_loop 流式集成测试

- [x] 8.1 agent_loop 单轮文本测试 — mock adapter.call_stream yield text_delta + done，验证 agent_loop yield 同样的事件序列，state.exit_reason=COMPLETED
- [x] 8.2 agent_loop 多轮 tool 测试 — mock call_stream 第一轮 yield tool_end，第二轮 yield text + done，验证 tool_result 事件和最终 COMPLETED
- [x] 8.3 agent_loop 消息累积测试 — 验证每轮结束后 state.messages 包含完整 assistant message（content + tool_calls）
- [x] 8.4 agent_loop abort 测试 — 设置 abort_signal，验证 state.exit_reason=ABORT
- [x] 8.5 agent_loop max_turns 测试 — 设置 max_turns=1，验证一轮后 state.exit_reason=MAX_TURNS
- [x] 8.6 agent_loop error 测试 — mock call_stream 抛异常，验证 yield error 事件且 state.exit_reason=ERROR
- [x] 8.7 agent_loop reactive compact 测试 — mock call_stream 抛 context_length_exceeded，验证 reactive_compact 被调用后重试
- [x] 8.8 run_agent_to_completion 测试 — 验证吞掉所有事件后返回正确 ExitReason

## 9. 测试 — 调用方适配回归测试

- [x] 9.1 spawn_agent 回归测试 — 验证 spawn 后子 agent 用 run_agent_to_completion 正确完成，通知队列收到消息
- [x] 9.2 pipeline engine 回归测试 — 验证线性/并行管线用 run_agent_to_completion 节点正确执行
- [x] 9.3 coordinator 回归测试 — 验证 coordinator_loop 作为 AsyncGenerator yield 事件，run_coordinator_to_completion 正常工作

## 10. 测试 — 真实 LLM 流式端到端测试

- [x] 10.1 OpenAI 真实流式测试 — 调用 OpenAI 兼容 API (light tier)，验证 call_stream yield text_delta 序列，最终 done 事件包含 usage
- [x] 10.2 Anthropic 真实流式测试 — 调用 Anthropic API (strong tier)，验证 call_stream yield text_delta 序列，done 包含 usage
- [x] 10.3 真实流式 tool call 测试 — 给 agent 一个需要调工具的任务，验证 tool_start → tool_delta → tool_end → tool_result → text_delta 完整事件链
- [x] 10.4 SSE 格式验证测试 — 收集所有 StreamEvent，调用 to_sse()，验证输出符合 `event: {type}\ndata: {json}\n\n` 格式规范
- [x] 10.5 agent_loop 端到端流式测试 — 完整 ReAct 循环（LLM → tool → LLM → done），验证消费者收到完整事件流且 state.messages 正确累积
