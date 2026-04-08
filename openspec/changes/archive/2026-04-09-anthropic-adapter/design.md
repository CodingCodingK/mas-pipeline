## Context

当前 LLM 层只有 `OpenAICompatAdapter`，所有 provider 都走 `/chat/completions` 端点。Anthropic API 是完全不同的协议：不同的 endpoint (`/v1/messages`)、不同的消息结构（system 独立、content blocks）、不同的认证方式（`x-api-key` header）。

已有基础设施：
- `LLMAdapter` ABC：定义 `call(messages, tools, **kwargs) -> LLMResponse`
- `LLMResponse` / `ToolCallRequest` / `Usage` 数据结构
- `router.py`：prefix 映射 + tier 解析
- `OpenAICompatAdapter`：完整的请求/响应/流式/重试逻辑

## Goals / Non-Goals

**Goals:**
- 实现 Anthropic Messages API adapter，让 `claude-*` 模型能真正调通
- 支持 tool_use（Anthropic 的 function calling 格式）
- 支持 extended thinking（thinking content blocks）
- 支持多模态输入（image content blocks）
- 复用已有的 `LLMAdapter` ABC 和 `LLMResponse` 数据结构
- 复用已有的重试逻辑模式

**Non-Goals:**
- 流式响应解析（Phase 5）
- Anthropic 的 prompt caching / batch API
- 修改 agent_loop 或 messages 存储格式（adapter 内部转换，对外透明）

## Decisions

### 1. 内部消息格式不变，adapter 内部做转换

内部 messages 继续用 OpenAI 格式（`role: system/user/assistant/tool`），`AnthropicAdapter.call()` 内部将 OpenAI 格式转为 Anthropic 格式发请求，响应解析回 `LLMResponse`。

**理由**：改内部格式影响 agent_loop、compact、session 等所有模块。adapter 的职责就是做格式转换，不应该把协议差异泄漏到上层。

**替代方案**：引入中间抽象层（如 `UnifiedMessage` 类）—— 过度设计，多一层间接性没有实际收益。

### 2. 多模态 content 的内部表示

用户/工具传入的 messages 中，content 字段可以是：
- `str`：纯文本（向后兼容）
- `list[dict]`：混合内容，每个 dict 是 `{type: "text", text: "..."}` 或 `{type: "image_url", image_url: {url: "data:..."}}`

这是 OpenAI 已有的格式规范。`AnthropicAdapter` 负责将 `image_url` 转为 Anthropic 的 `{type: "image", source: {type: "base64", media_type, data}}`。

`OpenAICompatAdapter` 不需要改——它本来就支持 content 为 list 的情况（直接传给 API）。

**理由**：不引入新的内部格式，复用 OpenAI 已有的 content blocks 规范。

### 3. 认证方式

Anthropic 用 `x-api-key` header 而非 `Authorization: Bearer`。在 adapter 初始化时设置正确的 header。

### 4. 请求/响应转换细节

**请求转换** (`_build_request`)：
1. 从 messages 中提取 system message → Anthropic `system` 参数
2. 合并相邻同角色消息（Anthropic 要求严格交替）
3. assistant tool_calls → `{type: "tool_use", id, name, input}` content blocks
4. role="tool" → `{type: "tool_result", tool_use_id, content}` 挂在 user message 下
5. image_url content blocks → `{type: "image", source: {type: "base64", media_type, data}}` 

**响应解析** (`_parse_response`)：
1. 遍历 response content blocks
2. `type: "text"` → `LLMResponse.content`
3. `type: "tool_use"` → `ToolCallRequest(id, name, arguments=input)`
4. `type: "thinking"` → `LLMResponse.thinking`
5. `stop_reason` 映射：`end_stop` → `stop`, `tool_use` → `tool_calls`

### 5. 重试逻辑复用

与 `OpenAICompatAdapter` 相同的重试策略：429/5xx 指数退避，3 次最大重试。代码结构相同但不抽基类——两个 adapter 的请求构造完全不同，抽象公共重试逻辑的收益不大。

### 6. Router 改造

`route()` 函数中，`_match_provider` 返回 provider name 后，根据 provider name 选择 adapter class：
- `"anthropic"` → `AnthropicAdapter`
- 其他 → `OpenAICompatAdapter`

## Risks / Trade-offs

- **[消息合并]** Anthropic 要求严格的 user/assistant 交替。如果内部 messages 有连续同角色消息（如多个 tool result），需要合并为一个消息的多个 content blocks → 在 `_build_request` 中处理
- **[base64 解析]** 需要从 OpenAI 的 data URI (`data:image/png;base64,xxx`) 中提取 media_type 和 raw base64 → 简单字符串解析
- **[thinking 兼容]** Anthropic extended thinking 需要传 `anthropic-beta: prompt-caching-2024-07-31` 或类似 header，且 thinking 有 budget_tokens 参数 → 通过 kwargs 传递，adapter 识别并设置
