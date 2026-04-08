## 1. AnthropicAdapter 核心

- [x] 1.1 创建 `src/llm/anthropic.py`，实现 `AnthropicAdapter` 类继承 `LLMAdapter`，初始化 httpx 客户端（x-api-key header, anthropic-version header）
- [x] 1.2 实现 `_build_request(messages, tools, **kwargs)`: system 提取、文本消息转换、相邻同角色合并、tools 格式转换
- [x] 1.3 实现 `_convert_tool_calls`: assistant tool_calls → tool_use content blocks
- [x] 1.4 实现 `_convert_tool_results`: role="tool" → user message 下的 tool_result content blocks
- [x] 1.5 实现 `_convert_multimodal`: image_url data URI → Anthropic image source（提取 media_type + base64 data）
- [x] 1.6 实现 `_parse_response(data)`: text/tool_use/thinking content blocks 解析 → LLMResponse，stop_reason 映射，usage 解析
- [x] 1.7 实现 `call()`: 组装请求 → POST /v1/messages → 解析响应，复用 429/5xx 重试逻辑（指数退避，3 次）

## 2. Extended Thinking

- [x] 2.1 实现 thinking 参数传递：kwargs 中的 `thinking` 参数写入请求体，设置 `anthropic-beta` header
- [x] 2.2 实现 thinking content block 解析：`{type: "thinking", thinking: "..."}` → `LLMResponse.thinking`，thinking tokens 写入 Usage

## 3. Router 改造

- [x] 3.1 修改 `src/llm/router.py` 的 `route()` 函数：当 provider 为 `"anthropic"` 时返回 `AnthropicAdapter`，其他不变

## 4. 测试

- [x] 4.1 编写 `scripts/test_anthropic_adapter.py`：请求构造测试（system 提取、tool_calls 转换、tool_result 转换、multimodal 转换、相邻消息合并）
- [x] 4.2 响应解析测试：text block、tool_use block、thinking block、usage 解析、stop_reason 映射
- [x] 4.3 router 测试：claude- 前缀返回 AnthropicAdapter、tier 解析后返回正确 adapter 类型
- [x] 4.4 回归测试：运行 `scripts/test_blog_pipeline.py` 确认无破坏
