## Context

Phase 6.x 就已经有了完整的 memory 基础设施：
- `memories` 表（PG，`project_id`/`type`/`name`/`description`/`content` 列）
- `src/memory/store.py` 的 CRUD（`list_memories` / `get_memory` / `write_memory` / `update_memory` / `delete_memory`）
- `src/memory/selector.py` 的 light-tier LLM 相关性预筛（`select_relevant`）
- `src/tools/builtins/memory.py` 的 `MemoryReadTool` / `MemoryWriteTool`

但 `src/agent/factory.py:142` 的 `build_system_prompt(role_body, skill_definitions=filtered_skills)` **从不传 `memory_context`**——整条链路是断的。Chat agent 跑起来后既看不到项目里有什么 memory，也不会主动写 memory。`_memory_layer` 函数写了但永远是 None-path。

本次改动的目的是填补这个接入点，把 CC 的 2-path 召回架构（MEMORY.md 索引 always-on + `findRelevantMemories` per-turn 预筛）移植进来。对齐详情在 `.plan/wrap_up_checklist.md` 任务 2.2 中讨论过三轮，用户批准的方案是："A+B 混合，走 CC 的同款"。

## Goals / Non-Goals

**Goals：**
- Chat agent 每轮都能感知"项目里有哪些 memory 存在"（Path A — always-on 索引注入）
- 每轮 user 发话前能把相关 memory 的完整 content 临时推给主 agent（Path B — per-turn selector）
- Chat agent 能在 LLM 判断值得长期记忆时自己调用 `memory_write` 写入；不引入 `memory_keeper` 独立 agent
- Path B 的临时注入不污染 PG——turn 结束 restore 原 user 消息
- Pipeline worker agent（analyzer / exam_generator / reviewer 等）行为零变化，零性能开销

**Non-Goals：**
- 不增加 UNIQUE(project_id, name) 约束——dedup 交给 LLM 在 `memory_write` 前调 `memory_read list` 完成（prompt 层要求）
- 不实现"reject → memory"的强制钩子——chat agent 在后续对话中自然读取 reject 反馈时会自主决定要不要记忆
- 不加前端 ResumePanel 的"同时记入项目偏好"复选框——被用户显式否决
- 不把 memory 注入给 pipeline worker agent——它们是短程执行者，长期记忆不属于它们的职责

## Decisions

### Decision 1：采用 CC 的 4 种 memory type，替换旧 4 种

CC 的 `{user, feedback, project, reference}` vs 我们当前的 `{fact, preference, context, instruction}`。

**选择：换成 CC 的 4 种。**

**Rationale：**
- CC 的分类经过 eval 迭代（可见 `memoryTypes.ts` 里的 H1/H5/H6 case 编号），边界更清晰
- CC 的 4 类对应明确语义（"关于用户/关于如何工作/关于项目/关于外部资源"），我们旧 4 类 `fact` 和 `context` 语义重叠
- `memories` 表当前 0 行，零迁移成本

**Alternatives considered：**
- 保留旧命名 → 不值得。CC 的 prompt 文本跟新命名绑定，混用会让 LLM 和 prompt 不对齐
- 两套并存 → 过度工程

### Decision 2：Path A 在 `factory.py` 系统 prompt 时注入

**选择：** `create_agent` 里加 `_load_memory_list(project_id, registry)`，返回三态：
- `None`（agent 没挂 memory 工具 or 没有 project_id）→ `_memory_layer` 返回 None，系统 prompt 零成本
- `""`（挂了但 list 为空）→ 注入指南+空态提示
- 非空 list → 注入指南+drift caveat+list

**Rationale：**
- 工具挂载与否决定了 agent 是否需要这块指南。Pipeline worker 没挂 memory 工具，短路返回 None，零额外 token
- 三态语义比布尔更表达力强——"挂了工具但没记忆"和"没挂工具"是本质不同的场景

**Alternatives considered：**
- 永远注入 → pipeline worker 白白多花 ~930 token 系统 prompt
- 只在 `memory_read` 存在时注入（忽略 `memory_write`）→ 未来可能有只读 agent，排除它们不合理

### Decision 3：Path B 用"临时覆盖 user 消息内容 + finally restore"实现

**选择：** `_overlay_recalled_memories` 改写最后一条 user 消息的 `content`，prepend 一个 `<recalled_memories>` 块；`finally` 块里 restore 原内容；`_persist_new_messages` 永远不会看到 overlay。

**Rationale：**
- `SessionRunner` 的持久化基于 `_pg_synced_count` 位置计数器——如果往 `state.messages` 中间 **插入** 新消息，位置会错位，导致后续 persist 重复写入。"改写内容不改变长度"避开了这个陷阱
- `try/finally` 保证 agent_loop 抛异常时也能 restore
- Restore 依赖 `last_user_idx` 在 agent_loop 期间不变——这对当前 agent_loop 成立（它只 append 到 tail）

**Alternatives considered：**
- 在 `last_user_idx` 位置插入独立的 system message → 位置计数器会错位，需要同时改 `_pg_synced_count` 逻辑，牵一发动全身
- 持久化 overlay → PG 会累积冗余，每轮都把 memory 写一遍进 conversation history
- 用独立的"attachments"抽象（像 CC 那样）→ 我们的 LLM adapter 不支持 attachments，需要新抽象层

### Decision 4：Selector 走 light-tier LLM，不升级到 medium/strong

**选择：** 沿用 `src/memory/selector.py:51` 已有的 `route("light")`，不改。

**Rationale：**
- MVP 阶段真实 memory 数量小（单项目几条到几十条），light tier 做分类任务够用
- 每轮聊天都跑一次 selector，延迟和成本敏感；light tier 显著更快更便宜
- 单行配置项，发现挑不准随时改 `route("medium")` 或 `route("strong")`，零代码重构

**Alternatives considered：**
- 学 CC 用 Sonnet-tier → 过度保守，真实场景不需要；如需要后续一行切换
- 完全不用 selector（Path A-only）→ 浪费了已有的 `selector.py`，也丢失了 content 级召回能力

### Decision 5：Memory 写入由主 chat agent 自发完成，不引入 memory_keeper 子 agent

**选择：** 给 chat agent（`assistant.md` / `coordinator.md`）的 `tools:` 加 `memory_read, memory_write`，LLM 自己判断何时记、记什么。

**Rationale：**
- CC 同款做法——`memdir.ts` 没有任何 `spawn`/`subagent` 调用，主 Claude 用 Write 工具直接写 memory 文件
- 多一个子 agent = 多一次 LLM 往返 + 额外 context 拷贝 + 多一套错误路径
- LLM 判断 + 读前 dedup 已足够；memory_guide 里"Before `action=write`, call `memory_read list` first"是 prompt 级的约束

**Alternatives considered：**
- 独立 memory_keeper agent → 复杂度不匹配收益
- 后端硬编码规则（"reject 自动 memory_write"）→ 脆弱，LLM 判断的灵活度丢失

### Decision 6：Memory 指南 token 预算 ~930（不追求 ~500）

**选择：** 指南文本 ~3700 chars / ~926 token（实测，砍过一轮）。

**Rationale：**
- 最初估算 ~500 偏乐观——4 种 type 的 description/when_to_save/example/body_structure 合起来天然占 700+ token
- 砍过一轮后保留：4 种 type 各 1 个 example（砍掉 2nd example）、`What NOT to save` 黑名单、`How to save` 的 dedup 规则、`When to use memory` 精简 2 条、全部 `body_structure` 字段
- 砍掉的：每种 type 的 2nd example、"Before acting on recalled memory"（与 drift caveat 重复）、开头"Build up this memory over time..."激励段、工具描述从 5 行压到 2 行
- 系统 prompt 由 provider 缓存跨轮复用，增量成本接近 0

**Alternatives considered：**
- 强压到 500 token → 需要砍 `when_to_save` / `body_structure`，LLM 会 under-save 或写出无结构的 memory，损失关键指导
- 保留全部 1510 token 原版 → 对 chat agent 成本显著，且大部分是重复内容

## Risks / Trade-offs

- **[Risk] `_overlay_recalled_memories` 依赖 agent_loop 只对 `state.messages` append 不做中间插入** → Mitigation: 在方法 docstring 写明这个不变式；如果未来 agent_loop 改成支持中间插入，restore 需要改成"按 id 查找"而不是"按 index 查找"
- **[Risk] Selector 用 light-tier LLM 挑选质量有限** → Mitigation: 单行可调——`src/memory/selector.py:51` 从 `route("light")` 改到 `route("medium")` 即可；真实使用中 2-3 周内收集到召回遗漏的 case 再决定升级
- **[Risk] BREAKING change：VALID_TYPES 重命名** → Mitigation: `memories` 表当前 0 行，没有真实数据要迁移；旧的 `fact/preference/context/instruction` 写入请求会被 `memory-store` 的 `ValueError` 拒绝，错误信息清晰；所有引用了旧类型名的文件（`scripts/test_memory_system.py`）同步更新
- **[Risk] Token 成本** → Mitigation: 只对挂了 memory 工具的 agent 注入，pipeline worker 零开销；指南 ~930 token 被 provider 缓存跨轮复用；Path B 每轮多一次 light-tier 调用（~200ms + ~0.0001 USD）
- **[Trade-off] Pipeline worker 不能写 memory** → 接受。长期记忆是 chat agent 的职责；pipeline worker 是短程执行者，它们的"记忆"通过 reject→chat 的隐式流程进入系统
- **[Trade-off] Memory list 在 system prompt 里按 insertion order 排序，不做相关性排序** → 接受。相关性排序的工作由 Path B selector 承担；list 的作用是"让 agent 知道有什么"

## Migration Plan

无数据迁移。`memories` 表当前 0 行。

**部署步骤：**
1. 合并本次 change（代码已就位，冒烟测试通过）
2. 重启 API 服务
3. 新建 chat session 时，`SessionRunner.start()` 调 `create_agent()`，看到 `assistant.md` 新的 `tools:` 列表，自动挂载 memory 工具，自动走 `_load_memory_list` → 注入指南
4. 第一次用户发话时，`_overlay_recalled_memories` 短路返回 None（memory 为空），正常走 agent_loop

**回滚：**
- `git revert` 本次 commit 即可；无 DB schema 变动；无索引变动；无第三方依赖变动

**End-to-end 验证：**（compose stack 起来之后）
1. 新建 project
2. 起 chat session，发一句 "以后输出都用中文，简明点"
3. 观察 chat agent 是否调了 `memory_write` 创建一条 `user` 或 `feedback` memory
4. 结束 session，开新 session 问同一 project 下的问题
5. 观察新 session 的 system prompt 是否出现 `## Current memories` 段落，以及是否包含刚写入的那条
6. 发一句相关的问题，观察 Path B overlay 是否把这条 memory 的 content 推给了主 agent

## Open Questions

（无——所有设计决策已在三轮讨论中和用户对齐）
