## Context

mas-pipeline 当前完成了 Phase 0（基础设施）：配置系统（`src/project/config.py`）、数据库连接层（`src/db.py`）、FastAPI 入口（`src/main.py`）。`config/settings.yaml` 已定义了 5 个 Provider（openai/gemini/deepseek/ollama/anthropic）和 3 个模型 tier（strong/medium/light）。

LLM Adapter 是 Phase 1 的第一个模块，Agent Loop（Phase 1.3）直接依赖它。

已有约束：
- Python 3.12，strict mypy
- httpx 已在依赖中，用于 HTTP 请求
- `Settings.providers: dict[str, ProviderConfig]` 提供 api_key + api_base
- `Settings.models: ModelsConfig` 提供 strong/medium/light → model name 映射

## Goals / Non-Goals

**Goals:**
- 统一所有 OpenAI 兼容 Provider 的调用接口，返回标准化的 `LLMResponse`
- 通过 model name 自动路由到正确的 Provider
- 内置重试机制处理瞬时故障（429/5xx）

**Non-Goals:**
- 流式输出（Phase 5）
- Anthropic 协议适配（Phase 4，独立协议）
- Embedding 调用（Phase 4 RAG 模块处理）
- 负载均衡 / failover / 多 Provider 降级

## Decisions

### D1: 统一返回结构用 dataclass 而非 dict

`LLMResponse` / `Usage` / `ToolCallRequest` 均为 `@dataclass`。

**理由**：dict 的 key 不可控——OpenAI 返回 `prompt_tokens`，Anthropic 返回 `input_tokens`。用 dataclass 在解析层统一翻译一次，下游零特殊分支。`Usage` 的三个字段（input_tokens / output_tokens / thinking_tokens）与 `telemetry_events` 表完全对齐。

**替代方案**：Pydantic model。比 dataclass 重，带来序列化/验证能力，但这里不需要——LLMResponse 是内部数据结构，不走网络传输。

### D2: ABC 只定义 call()，不定义 call_stream()

Phase 1 的 `LLMAdapter` ABC 只有一个抽象方法 `call()`。

**理由**：流式是 Phase 5 的事。子类总共 2-3 个（openai_compat / anthropic / 可能 mock），到时加方法改动量极小。不为假设的未来付今天的复杂度。

### D3: call() 签名用 **kwargs 透传

```python
async def call(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse
```

**理由**：调用点基本只有 Agent Loop 一处，不是公共 API。kwargs 允许 temperature / max_tokens / top_p 等参数直接透传到 HTTP 请求体，无需维护一个 Options 对象。

**替代方案**：CallOptions dataclass。带来类型安全和 IDE 补全，但对只有一个调用点的内部接口是过度设计。

### D4: Router 使用硬编码前缀 dict

```python
_PREFIX_MAP = {
    "gpt-": "openai", "o1-": "openai", "o3-": "openai",
    "claude-": "anthropic",
    "gemini-": "gemini",
    "deepseek-": "deepseek",
}
```

匹配不到 → 报错，不猜。Ollama 模型名没有统一前缀，通过配置显式指定 provider。

**理由**：模型名前缀和 Provider 的对应关系是稳定的，硬编码比通用匹配引擎简单一个数量级。新模型来了加一行。

**替代方案**：配置中显式声明每个 model → provider 映射。更灵活但更啰嗦，对于已知的主流 Provider 没有必要。

### D5: 重试机制自己写，不引入 tenacity

for 循环 + exponential backoff（1s → 2s → 4s），最多 3 次。只重试 429 和 5xx，其他错误直接抛。

**理由**：逻辑简单（十几行代码），不值得引入新依赖。httpx 自带的 transport 重试只处理连接级错误，不覆盖 HTTP 状态码。

## Risks / Trade-offs

- **[Ollama 模型名无统一前缀]** → Router 需要支持配置覆盖或 fallback provider 机制。当前方案：匹配不到就报错，用户在配置中显式指定。
- **[DeepSeek thinking 格式可能变化]** → thinking 字段设为 `str | None`，解析层做防御性处理。
- **[kwargs 无类型检查]** → 拼错参数名不会报错。可接受，因为调用点极少且都在内部代码中。
