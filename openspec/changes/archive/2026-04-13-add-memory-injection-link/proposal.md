## Why

Phase 6.x 已经有 `memory_read` / `memory_write` 工具和 `memories` 表，但**没有任何路径把它们接进 agent 的 runtime**——`src/agent/factory.py:142` 的 `build_system_prompt()` 调用从不传 `memory_context`，chat agent 根本看不到项目里有什么 memory，也不知道自己能写。结果是 checklist 2.2 列出的"记忆系统已就绪但空转"的状态：数据层、工具层、召回层全部存在，但长期记忆对 agent 的实际行为零贡献。

本次改动把 Claude Code 的两路召回架构（CC 的 `MEMORY.md` always-on 索引 + `findRelevantMemories` per-turn 预筛）落进我们的 PG 后端，填补 factory / session_runner 两个接入点。

## What Changes

- **BREAKING** `memory-store` 的类型枚举从 `{fact, preference, context, instruction}` 改成 CC 的 `{user, feedback, project, reference}`——现有 `memories` 表为空，无迁移数据，但 API 形状变了
- `memory-tools` 的 `memory_write.type` 参数加 `enum` 约束，`description` 按新 4 种类型重写语义
- `context-builder` 新增 `_MEMORY_GUIDE` 常量（~930 token 的 CC 风格行为指南）和 `_memory_layer` 的三态语义（`None` 不注入 / `""` 注入指南+空态提示 / 非空注入指南+drift caveat+list）
- `agent-factory` 在 `create_agent` 里新增 `_load_memory_list()`，**只对注册了 `memory_read`/`memory_write` 工具的 agent** 从 PG 拉 list 并注入系统 prompt（Path A）
- `session-runner` 在每轮 `agent_loop` 前调用 `_overlay_recalled_memories()`，用现有 `src/memory/selector.py` 的 light-tier LLM 挑 top-K 相关 memory，把 content 作为 `<recalled_memories>` 块临时 prepend 到最后一条 user 消息上，turn 结束 restore（Path B），PG 永远不会持久化 overlay
- `agents/assistant.md` 和 `agents/coordinator.md` 的 `tools:` frontmatter 加入 `memory_read, memory_write`；pipeline 内部 worker agent（analyzer / exam_generator / reviewer / writer / researcher / parser）**不加**——它们是短程执行者，不应写长期记忆

## Capabilities

### New Capabilities

（无——这次全部是对已有 capability 的扩展/修改）

### Modified Capabilities

- `memory-store`: VALID_TYPES 枚举重命名（BREAKING），由 CC 的 4 类替换旧 4 类
- `memory-tools`: `memory_write` 工具的 `type` 参数加 enum 约束并同步 description 语义
- `context-builder`: 新增"project memory 指南 + 当前 memory list"层，`_memory_layer` 从 2 态升到 3 态（None / "" / 非空）
- `agent-factory`: `create_agent` 在检测到 memory 工具在场时加载 memory list 注入 system prompt
- `session-runner`: 在每轮 agent_loop 之前用 selector 挑选相关 memory 并临时 overlay 到最后一条 user 消息，turn 后 restore

## Impact

**代码（已经动过了，本次 change 反追文档）**：
- `src/memory/store.py:15` — `VALID_TYPES` 重命名
- `src/tools/builtins/memory.py:76-88` — `MemoryWriteTool` type 参数加 enum
- `src/agent/context.py` — 新增 `_MEMORY_GUIDE` 常量 + `_memory_layer` 三态语义
- `src/agent/factory.py:142` — 调用 `_load_memory_list` 并注入；新增 helper 函数
- `src/engine/session_runner.py:234` — 新增 `_overlay_recalled_memories` 调用 + restore `finally`；新增方法
- `agents/assistant.md` / `agents/coordinator.md` — frontmatter `tools:` 列表扩展
- `scripts/test_memory_system.py` — 跟进 VALID_TYPES 断言

**行为**：
- Chat agent（assistant/coordinator）现在每轮对话都能看到项目 memory list（Path A），并能在 LLM 判断值得记忆时调 `memory_write` 落库
- 每轮对话前 selector 会基于用户最新一句话挑最相关的 ≤5 条 memory 的完整 content 临时注入（Path B），帮主 agent 快速定位
- Pipeline worker agent 行为零变化——它们没被挂 memory 工具，`_load_memory_list` 直接短路返回 None

**性能**：
- Chat agent system prompt 增加约 1040 token（指南 ~926 + list ~100 估算），provider 缓存命中后跨轮复用
- 每轮额外一次 light-tier LLM 调用（selector），延迟可感但可接受；list 为空时 Path B 完全短路
- Pipeline 场景零开销

**风险**：
- `_overlay_recalled_memories` 依赖 `agent_loop` 只对 `state.messages` append 不做中间插入的不变式；若未来 agent_loop 改架构，restore 会错位
- Selector 用 light-tier LLM 挑选，质量可能低于 CC 的 Sonnet-tier；真实使用中如发现召回挑不准，可把 `src/memory/selector.py:51` 的 `route("light")` 改成 `route("medium")` 单点调整
