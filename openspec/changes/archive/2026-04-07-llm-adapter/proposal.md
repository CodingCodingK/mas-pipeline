## Why

mas-pipeline 是一个多 Agent 内容生产管线引擎，所有 Agent 的核心能力依赖 LLM 调用。当前项目只完成了基础设施（Phase 0），没有 LLM 调用层，整个系统无法运行。需要一个统一的 LLM Adapter 层，屏蔽不同 Provider 的协议差异，让上层 Agent Loop 只面对一个接口。

## What Changes

- 新增 `LLMResponse`、`Usage`、`ToolCallRequest` 数据结构，作为所有 LLM 调用的统一返回格式
- 新增 `LLMAdapter` 抽象基类，定义 `call()` 方法签名
- 新增 OpenAI 兼容层实现，支持 OpenAI、DeepSeek、Ollama、Gemini 四个 Provider
- 新增 Router，通过 model name 前缀自动路由到对应 Provider 的 Adapter 实例
- 内置错误重试机制（429/5xx 指数退避，最多 3 次）

## Capabilities

### New Capabilities
- `llm-call`: 统一的 LLM 调用接口——数据结构定义（LLMResponse/Usage/ToolCallRequest）、LLMAdapter ABC、OpenAI 兼容层实现
- `llm-routing`: Model name 到 Provider 的路由——前缀匹配注册表、从配置系统读取 Provider 信息、构造 Adapter 实例

### Modified Capabilities

（无已有 capability 被修改）

## Impact

- **新增文件**：`src/llm/adapter.py`、`src/llm/openai_compat.py`、`src/llm/router.py`（已有空文件）
- **依赖读取**：`src/project/config.py` 的 `Settings.providers` 和 `Settings.models`
- **外部依赖**：使用已有的 `httpx` 库，不引入新依赖
- **下游影响**：Phase 1.3 Agent Loop 将依赖此模块调用 LLM
