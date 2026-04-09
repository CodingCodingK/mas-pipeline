## Context

当前 LLM 调用链：`agent_loop` → `adapter.call()` → 阻塞等待完整 LLMResponse → 处理 tool_calls → 循环。OpenAICompatAdapter 已有 `_request_stream()` 但仅作 fallback，消费 SSE 后重组为完整 dict 返回，调用方感知不到流式。

Phase 1 的 LLMAdapter ABC 只定义了 `call()`，未定义 `call_stream()`。agent_loop 返回 `ExitReason`，所有调用方（spawn_agent、pipeline engine、coordinator）都用 `await agent_loop(state)` 同步等结果。

竞品调研结论（详见 `.plan/streaming_design_notes.md` 第 8 节）：
- LiteLLM 排除（供应链安全事故 + 重依赖）
- Pydantic AI 不用但学两层分离架构（Model Streaming + UI Streaming）
- 自研 ~200 行核心代码，零新依赖
- 我们的 StreamEvent 事件类型与 AG-UI 协议自然对齐

## Goals / Non-Goals

**Goals:**
- 两个 adapter 各实现 `call_stream()` — 将原生 SSE 逐条翻译为统一 StreamEvent
- agent_loop 改为 AsyncGenerator，永远流式（CC 做法）
- 确定 API 层 SSE 输出格式，Phase 6 直接用
- 不关心流式的调用方有简单的 helper 可用

**Non-Goals:**
- 不实现 FastAPI SSE endpoint（Phase 6）
- 不实现 WebSocket 推送（Phase 6）
- 不实现 StreamingToolExecutor（CC 的工具与流并发执行，复杂度高，收益有限）
- 不接入 AG-UI 协议（Phase 6-7 前端时按需接入）

## Decisions

### D1: StreamEvent 作为统一流式事件类型

**选择**：定义 `StreamEvent` dataclass，两个 adapter 各自翻译原生 SSE 为 StreamEvent。

**替代方案**：
- A) 直接暴露原生 SSE chunk（OpenAI dict / Anthropic dict）→ 上层必须知道底层是哪个 provider，破坏抽象
- B) 用 LiteLLM 统一为 OpenAI chunk 格式 → 供应链风险 + 无法包含 agent 层事件

**StreamEvent 类型**：

| type | 含义 | 关键字段 |
|------|------|----------|
| text_delta | 文本片段 | content |
| thinking_delta | 思考片段 | content |
| tool_start | 工具调用开始 | tool_call_id, name |
| tool_delta | 工具参数片段 | content (JSON 片段) |
| tool_end | 工具参数完整 | tool_call: ToolCallRequest |
| tool_result | 工具执行结果 | tool_call_id, output, success |
| usage | token 用量 | usage: Usage |
| done | 流结束 | finish_reason |
| error | 出错 | content |

注：`tool_result` 是 agent_loop 层产生的，不是 adapter 层。

### D2: agent_loop 永远流式，改为 AsyncGenerator

**选择**：agent_loop 从 `async def agent_loop(state) -> ExitReason` 改为 `async def agent_loop(state) -> AsyncGenerator[StreamEvent, None, None]`。

**替代方案**：
- A) 双模式 `agent_loop(state, stream=True/False)` → 两套逻辑，维护成本高
- CC 的做法也是永远流式

**调用方适配**：新增 `run_agent_to_completion(state) -> ExitReason` helper：
```
async def run_agent_to_completion(state):
    async for event in agent_loop(state):
        pass  # 吞掉所有事件
    return state.exit_reason
```

spawn_agent、pipeline engine、coordinator 改用此 helper，行为不变。

### D3: adapter.call() 保留，call_stream() 新增

**选择**：LLMAdapter ABC 同时保留 `call()` 和 `call_stream()`。

**理由**：
- `call()` 仍有使用场景：compact 摘要、memory relevance 判断等不需要流式的内部调用
- 现有 `_request_stream()` 保留作为 `call()` 的 fallback（服务器强制 stream 时重组为完整响应）
- `call_stream()` 是新方法，不改变 `call()` 的行为

### D4: ExitReason 改为通过 state 传递

**选择**：agent_loop 作为 generator 不再 return ExitReason，改为在 state 上设置 `state.exit_reason`。generator 结束时调用方读 `state.exit_reason`。

**理由**：Python generator 的 return 值需要通过 `StopAsyncIteration.value` 获取，API 不友好。放在 state 上更直观。

### D5: API 层 SSE 格式现在确定

**选择**：SSE 格式遵循标准 `event: <type>\ndata: <json>\n\n`，事件类型与 StreamEvent.type 一一对应。

```
event: text_delta
data: {"content": "你好"}

event: tool_start
data: {"tool_call_id": "call_xxx", "name": "read_file"}

event: tool_end
data: {"tool_call_id": "call_xxx", "name": "read_file", "arguments": {"path": "/a"}}

event: tool_result
data: {"tool_call_id": "call_xxx", "output": "file content...", "success": true}

event: usage
data: {"input_tokens": 120, "output_tokens": 45, "thinking_tokens": 0}

event: done
data: {"finish_reason": "completed"}
```

与 AG-UI 协议事件类型高度对齐（TEXT_MESSAGE_CONTENT ↔ text_delta, TOOL_CALL_START ↔ tool_start 等），Phase 6 前端时可低成本接入。

### D6: 两层分离架构（参考 Pydantic AI）

```
  第 1 层：Model Streaming（本次实现）
  ─────────────────────────────────────
  OpenAICompatAdapter.call_stream()  /  AnthropicAdapter.call_stream()
       → AsyncIterator[StreamEvent]

  第 2 层：UI Streaming（Phase 6 实现）
  ─────────────────────────────────────
  StreamEvent → SSE / WebSocket / AG-UI
```

本次只做第 1 层 + agent_loop 改造。第 2 层是纯格式转换，Phase 6 加。

## Risks / Trade-offs

**[agent_loop 签名变更影响面广] → 逐个适配调用方**
agent_loop 从函数变为 generator，所有调用方都要改。但调用方数量有限（spawn_agent、pipeline engine、coordinator），且都改为调 `run_agent_to_completion()` 即可，改动量小。

**[流式下 compact 时机变化] → 保持循环间 compact 不变**
当前 compact 在每轮循环开头做。流式化后，一轮内部变成 `async for event in call_stream()` + tool dispatch，compact 仍在轮与轮之间做，时机不变。

**[tool_call 参数不完整时不能执行] → tool_end 时才 dispatch**
流式 tool_call 是分片到达的（tool_start → tool_delta → tool_end）。必须等 tool_end（参数完整）才能执行工具，不能提前执行。这比 CC 的 StreamingToolExecutor 简单但延迟略高，可接受。

**[SSE 连接中断] → adapter 层 retry 不变**
`call_stream()` 在 HTTP 层如果遇到 429/5xx，走现有 retry 逻辑。SSE 流中途断开视为 error，yield StreamEvent(type="error")，agent_loop 决定是否 retry 整轮。
