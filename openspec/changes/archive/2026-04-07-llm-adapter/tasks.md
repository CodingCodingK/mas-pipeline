## 1. 数据结构（src/llm/adapter.py）

- [x] 1.1 实现 `Usage` dataclass（input_tokens, output_tokens, thinking_tokens）
- [x] 1.2 实现 `ToolCallRequest` dataclass（id, name, arguments）
- [x] 1.3 实现 `LLMResponse` dataclass（content, tool_calls, finish_reason, usage, thinking）
- [x] 1.4 实现 `LLMAdapter` ABC，定义 `call(messages, tools=None, **kwargs) -> LLMResponse`

## 2. OpenAI 兼容层（src/llm/openai_compat.py）

- [x] 2.1 实现 `OpenAICompatAdapter.__init__(api_base, api_key, model)`，创建 httpx.AsyncClient
- [x] 2.2 实现请求构造：messages + tools + kwargs → OpenAI chat/completions 请求体
- [x] 2.3 实现响应解析：OpenAI JSON → LLMResponse（含 token 字段翻译 prompt_tokens → input_tokens）
- [x] 2.4 实现 tool_calls 解析：提取 id/name/arguments，arguments JSON string → dict
- [x] 2.5 实现 thinking 解析：DeepSeek reasoning_content → LLMResponse.thinking
- [x] 2.6 实现重试机制：429/5xx 指数退避（1s→2s→4s），最多 3 次，其他错误直接抛

## 3. Router（src/llm/router.py）

- [x] 3.1 实现前缀映射表 `_PREFIX_MAP`（gpt-/o1-/o3- → openai, claude- → anthropic, gemini- → gemini, deepseek- → deepseek）
- [x] 3.2 实现 tier 解析：strong/medium/light → Settings.models 对应的 model name
- [x] 3.3 实现 `route(model_name) -> LLMAdapter`：tier 解析 → 前缀匹配 → 从 Settings.providers 读配置 → 构造 OpenAICompatAdapter
- [x] 3.4 实现错误处理：未知 model name 或未配置 provider 时抛 ValueError

## 4. 验证

- [x] 4.1 编写验证脚本，调通任一 Provider（OpenAI/DeepSeek/Gemini/Ollama），确认 LLMResponse 结构正确
