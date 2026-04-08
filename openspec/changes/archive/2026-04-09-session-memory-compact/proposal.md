## Why

当前 Agent 执行的所有 messages 仅存于内存 list，执行结束即丢失。长时间运行的 coordinator 会因 context window 溢出而失败。Agent 无法跨会话记住信息。Phase 3 补齐这三块基础能力：Session 持久化、Memory 跨会话记忆、Compact 对话压缩。

## What Changes

- **Session Manager**：Conversation（PG 持久化跨 run 用户对话历史）+ Agent Session（Redis 热存实时消息 + PG 冷归档 + TTL 24h 自动过期）+ 孤儿 tool_result 清理
- **Memory System**：project 级记忆 CRUD（写入/更新/删除/列出/读取）+ LLM 相关性筛选（select_relevant）+ MemoryReadTool / MemoryWriteTool 两个 LLM 工具 + 接入 context_builder `_memory_layer`
- **Compact 对话压缩**：三级机制——microcompact（每轮清理旧 tool_result）、autocompact（token 超阈值 fork 轻模型生成摘要）、reactive（LLM 报 context_length_exceeded 时紧急压缩）
- **Token 估算 + 阈值计算**：基于模型 context_window 的百分比阈值，内置常见模型默认值 + settings.yaml 可覆盖配置
- **Agent Loop 集成**：填充现有 3 个 compact 占位注释，新增 TOKEN_LIMIT ExitReason

## Capabilities

### New Capabilities
- `session-manager`: Conversation PG CRUD（原 user_sessions → conversations 表）+ Agent Session Redis 热存/PG 冷归档/TTL 管理 + 孤儿消息清理
- `memory-store`: 记忆 CRUD（write/update/delete/list/get）+ LLM 相关性筛选 select_relevant
- `memory-tools`: MemoryReadTool + MemoryWriteTool，Agent 可通过工具读写记忆
- `compact`: microcompact / autocompact / reactive 三级压缩 + token 估算 + 阈值计算

### Modified Capabilities
- `agent-loop`: 接入 compact 预处理（microcompact + autocompact + blocking_limit）、reactive compact、新增 TOKEN_LIMIT ExitReason
- `context-builder`: `_memory_layer` 从返回 None 改为注入相关记忆
- `tool-builtins`: get_all_tools() 新增 memory_read + memory_write 两个工具

## Impact

- **新文件**：`src/session/manager.py`, `src/memory/store.py`, `src/memory/selector.py`, `src/agent/compact.py`, `src/tools/builtins/memory.py`
- **修改文件**：`src/agent/loop.py`（compact 集成）, `src/agent/state.py`（TOKEN_LIMIT）, `src/agent/context.py`（memory_layer）, `src/tools/builtins/__init__.py`（新增工具）, `config/settings.yaml`（compact 百分比配置 + context_windows 可选配置）, `src/project/config.py`（Settings model 新增字段）
- **DB 表**：`user_sessions` 重命名为 `conversations`，使用已有的 `agent_sessions`, `memories`, `compact_summaries` 表
- **外部依赖**：Redis（Agent Session 热存）、tiktoken 或字符估算（token 计数）
- **ORM**：新增 Conversation, AgentSessionRecord, Memory, CompactSummary 四个 ORM model
