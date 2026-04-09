## Why

当前所有 LLM 调用都是阻塞式 — 等待完整响应后才返回。用户在 5-30 秒内看不到任何输出，体验差。流式输出让 agent 逐 token 显示回复、实时展示工具调用过程，是 Phase 5 体验提升最大的模块。Phase 1 已在 LLMAdapter ABC 中为 `call_stream` 留了占位，现在兑现。

## What Changes

- 新增 `StreamEvent` 统一流式事件类型，两个 adapter（OpenAI / Anthropic）各自将原生 SSE 逐条翻译为 StreamEvent 并 yield
- LLMAdapter ABC 新增 `call_stream()` 抽象方法，返回 `AsyncIterator[StreamEvent]`
- OpenAICompatAdapter 新增 `call_stream()` — 解析 OpenAI SSE delta，逐条翻译为 StreamEvent
- AnthropicAdapter 新增 `call_stream()` — 解析 Anthropic content_block_start/delta/stop，逐条翻译为 StreamEvent
- **agent_loop 改为永远流式** — 从 `async def → ExitReason` 改为 `AsyncGenerator[StreamEvent]`，所有调用方通过 `async for` 消费事件流
- 新增 `run_agent_to_completion()` helper — 吞掉事件流只取最终结果，供 pipeline engine、spawn_agent 等不关心流式的调用方使用
- 确定 API 层 SSE 输出格式（Phase 6 直接用，本次不实现 API endpoint）

## Capabilities

### New Capabilities
- `stream-events`: StreamEvent 类型定义 + adapter call_stream() 流式翻译规范
- `stream-agent-loop`: agent_loop AsyncGenerator 改造 + run_agent_to_completion helper

### Modified Capabilities
- `llm-call`: LLMAdapter ABC 新增 call_stream() 抽象方法
- `agent-loop`: agent_loop 签名从 `async def → ExitReason` 改为 `AsyncGenerator[StreamEvent, None, None]`
- `spawn-agent`: 调用方从 `await agent_loop(state)` 改为 `await run_agent_to_completion(state)`
- `pipeline-execution`: 同上，节点执行改用 run_agent_to_completion
- `coordinator-loop`: 同上

## Impact

- **代码**：`src/llm/adapter.py`, `src/llm/openai_compat.py`, `src/llm/anthropic.py`, `src/agent/loop.py`, `src/agent/factory.py`, `src/tools/builtins/spawn_agent.py`, `src/engine/pipeline.py`, `src/engine/coordinator.py`
- **新文件**：`src/streaming/events.py`（StreamEvent 定义）
- **API**：本次不新增 HTTP endpoint，但确定 SSE 格式供 Phase 6 使用
- **依赖**：零新依赖
