## Why

当前 router 对所有 provider（包括 `claude-` 前缀）都返回 `OpenAICompatAdapter`，但 Anthropic API 不兼容 OpenAI 格式——endpoint、消息结构、tool 调用格式、thinking 格式、多模态格式全部不同。这意味着 `settings.yaml` 中配的 `medium: claude-sonnet-4-6` 实际上跑不通。

Phase 4 需要 Claude 作为主力 medium tier 模型，且后续 courseware pipeline 需要多模态能力（图片直传 LLM），必须实现 Anthropic 原生 adapter。

## What Changes

- 新增 `AnthropicAdapter`：实现 Anthropic Messages API 的请求构造、响应解析、thinking block 处理、多模态 content blocks 转换
- 修改 `router.py`：`claude-` 前缀路由到 `AnthropicAdapter` 而非 `OpenAICompatAdapter`
- 内部消息格式扩展：content 字段从纯 `str` 扩展为 `str | list[block]`，支持 text + image 混合内容

## Capabilities

### New Capabilities
- `anthropic-messages`: Anthropic Messages API adapter，包括请求/响应格式转换、tool_use、thinking、multimodal content blocks

### Modified Capabilities
- `llm-routing`: router 需要根据 `claude-` 前缀返回 `AnthropicAdapter` 而非 `OpenAICompatAdapter`

## Impact

- `src/llm/anthropic.py` — 新文件
- `src/llm/router.py` — 修改 route() 函数，新增 AnthropicAdapter 导入和分支
- `src/llm/adapter.py` — LLMResponse 不变，但 content 语义扩展（上游传入的 messages content 可能是 list）
- 依赖：`httpx`（已有），无新依赖
- 测试：需新增 anthropic adapter 验证脚本
