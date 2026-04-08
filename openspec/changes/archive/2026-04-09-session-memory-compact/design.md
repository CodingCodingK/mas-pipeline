## Context

Phase 2 完成后，Agent 的所有 messages 仅存在于内存 `AgentState.messages` list。长运行的 coordinator 会因 context window 溢出失败，Agent 无法跨会话记住信息。

已有基础设施：
- DB 表已建好：`user_sessions`（将重命名为 `conversations`）, `agent_sessions`, `memories`, `compact_summaries`
- `agent_loop.py` 有 3 个 compact 占位注释
- `context.py` 的 `_memory_layer()` 返回 None（占位）
- `AgentState.has_attempted_reactive_compact` 已预留
- Redis 已部署（docker-compose）

## Goals / Non-Goals

**Goals:**
- Session 持久化：Conversation (PG, 用户对话历史) + Agent Session (Redis 热存 + PG 冷归档)
- Memory：project 级记忆 CRUD + LLM 相关性筛选 + Agent 工具
- Compact：三级压缩机制，解决 coordinator 长对话溢出问题
- 阈值配置化：百分比 + 模型 context_window 内置默认值 + settings.yaml 可覆盖

**Non-Goals:**
- Agent 崩溃恢复（Phase 5 鲁棒性）
- Embedding 向量相关性搜索（Phase 4 RAG）
- MCP 工具扩展（Phase 5）
- Streaming compact（Phase 5）
- tiktoken 精确 token 计数（字符近似足够）

## Decisions

### D1: Agent Session 使用 Redis List + PG 归档

**选择**: Redis RPUSH 实时写 + 完成后归档到 PG `agent_sessions` 表

**替代方案**: 只用 PG（Agent 结束后一次性写入）
- 优点更简单，但不支持执行中断恢复
- 用户明确选择了 Redis 热存方案

**实现**: `src/session/manager.py`，Redis key 格式 `agent_session:{agent_id}`，TTL 从 `settings.session.agent_ttl_hours` 读取（默认 24h）。

### D2: Context window 三级查找

**选择**: settings.yaml 配置 > 硬编码默认表 > 128000 兜底

```python
# src/agent/compact.py
_DEFAULT_CONTEXT_WINDOWS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-6": 200000,
    "claude-haiku-4-5": 200000,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
}
DEFAULT_CONTEXT_WINDOW = 128000
```

**替代方案**: 调 `/v1/models` API 动态查询
- 不是所有 provider/proxy 都支持，不可靠
- 用户确认配置优先 + 默认值方案

### D3: Compact 阈值用百分比

**选择**: 百分比配置，替换原有的绝对值 buffer

```yaml
# settings.yaml
compact:
  autocompact_pct: 0.85    # 超 85% 触发 autocompact
  blocking_pct: 0.95       # 超 95% 硬阻断
  micro_keep_recent: 3     # microcompact 保留最近 3 条 tool_result
```

计算: `threshold = context_window * pct`

**替代方案**: 保留原来的绝对值 buffer（`output_reserve: 20000` 等）
- 绝对值对 128K 模型合理，对 1M 模型不合理
- 百分比更通用

### D4: Token 估算用字符近似

**选择**: `len(json.dumps(msg, ensure_ascii=False)) / 4`

**替代方案**: tiktoken
- 需要额外依赖，不同模型需要不同编码器
- 字符近似误差 ~20%，对阈值判断足够（阈值本身就是估值）
- 未来可选升级，不影响接口

### D5: Memory select_relevant 用 LLM 判断

**选择**: 调 light-tier LLM 判断相关性

**替代方案**: pgvector embedding cosine 相似度
- 需要 embedding 管线（Phase 4 RAG 才做）
- LLM 判断更准确（理解语义而非向量距离）
- 代价是每次 Agent 启动多一次 LLM 调用

**Prompt 设计**: 给 LLM 所有 memory 的 name + description 列表 + 当前 query，返回相关 memory ID 的 JSON 数组。

### D6: Autocompact 摘要 prompt 参考 CC

摘要 prompt 要求 LLM 保留：
- 关键决策和结论
- 文件路径和代码片段
- 错误信息和修复方案
- 任务进度和状态
- 用户偏好和指令

返回格式: 结构化 Markdown 摘要，作为单条 `{"role": "user", "content": "[CONVERSATION SUMMARY]\n..."}` 注入。

### D7: context_length_exceeded 错误检测

OpenAI 协议的 context 超限错误与 Anthropic 不同：
- OpenAI: HTTP 400 + error.code = "context_length_exceeded"
- Anthropic: HTTP 400 + error.type = "prompt_too_long" (Phase 4)

在 `agent_loop` 中捕获 adapter 异常，检查错误消息中是否包含 `"context_length_exceeded"` 或 `"prompt_too_long"` 关键词。

### D8: Compact 集成到 agent_loop 的位置

```
agent_loop iteration:
  ┌─ micro_compact(messages)           ← 每轮清理旧 tool_result
  ├─ tokens = estimate_tokens(messages)
  ├─ if tokens > blocking_limit → TOKEN_LIMIT
  ├─ if tokens > autocompact → auto_compact → replace messages
  ├─ if still > blocking_limit → TOKEN_LIMIT
  │
  ├─ abort check
  ├─ LLM call
  │   └─ on context_length_exceeded:
  │       if !has_attempted_reactive → reactive_compact → continue
  │       else → TOKEN_LIMIT
  │
  ├─ append assistant message
  ├─ dispatch tools
  ├─ append tool results
  ├─ abort check
  └─ turn accounting
```

### D9: User Session 重命名为 Conversation

**选择**: `user_sessions` 表重命名为 `conversations`，ORM model 从 `UserSession` 改为 `Conversation`，API 函数从 `create_session` 改为 `create_conversation`。

**原因**: "User Session" 和 "Agent Session" 都叫 Session 有歧义。用户对话历史本质是 Conversation，Agent 执行期间的 LLM 交互才是 Session。

**影响范围**: `scripts/init_db.sql`（表名 + FK + 索引名），`src/models.py`（ORM class），`src/session/manager.py`（函数名），`workflow_runs.session_id` FK 引用。

## Risks / Trade-offs

**[Risk] Redis 不可用时 Agent Session 丢失** → 短期可接受（Agent 仍能运行，只是没有持久化）。Phase 5 加 Redis 健康检查和降级策略。

**[Risk] LLM select_relevant 增加启动延迟** → light-tier 模型调用通常 <1s，可接受。如果 memory 数量极多（>100），分页或预筛选。

**[Risk] 字符近似 token 估算误差** → 阈值本身是安全边界，20% 误差不会导致硬故障。最坏情况是 autocompact 提前/延迟触发一轮。

**[Risk] Autocompact 摘要丢失关键信息** → 通过 prompt 明确要求保留关键类别。摘要存入 compact_summaries 表可事后审计。

**[Trade-off] Memory scope 限定 project 级** → 不支持跨 project 记忆共享。这是有意的——project 隔离是安全边界。
