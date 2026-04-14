## Context

当前 `agent_runs` 表只存 `role / description / status / result / owner / metadata_`,其中 `result` 是"最后一条 assistant 文字"。两条路径同构地写这张表:

- **spawn_agent 路径**(`src/tools/builtins/spawn_agent.py:_run_agent_background`):chat 场景下主 agent 通过 `spawn_agent` 工具异步派生子 agent,fire-and-forget,结束后把结果作为 `<task-notification>` XML 消息追加到父 Conversation
- **pipeline 路径**(`src/engine/pipeline.py:_run_node`):pipeline 每个节点创建一个 agent,跑完把 output 作为节点 output 传给下游

两条路径都调用 `create_agent_run → run_agent_to_completion → complete_agent_run` 三段式。三段式中间的 `state.messages`(agent loop 完整消息流)在 `run_agent_to_completion` 里只被用来抽取最后一条文字,然后随协程释放而丢弃。

CC 的对齐做法是把 transcript 独立持久化(`subagents/agent-<agentId>.jsonl`,`isSidechain: true`),同时把 `totalToolUseCount / totalDurationMs / totalTokens / usage` 随 `AgentToolResult` 返回给主 agent。主 agent 的 LLM 上下文**只看到**这几个字段,**永远不读** transcript —— 这是强隔离,防止子 agent 的 token 成本回灌主上下文。

## Goals / Non-Goals

**Goals:**

- **后端数据对齐**:`agent_runs` 存完整 transcript + 三个统计指标(tool_use_count / total_tokens / duration_ms),两条路径同时受益
- **主 agent 看得到统计数字**:`<task-notification>` XML 追加三字段,让主 agent 在下一 turn 能做 cost-aware 决策
- **分析页可视化**:新 REST endpoint + 共享前端抽屉组件,chat 和 pipeline 两个分析页都能点进去看子 agent 完整过程
- **两条路径对称**:改动集中在 `agent-run-lifecycle` + `agent-loop` 两个底层能力,调用点(spawn_agent / pipeline)只是传参升级

**Non-Goals:**

- ❌ **主 agent 读 transcript** —— 绝对不把 `agent_runs.messages` 注入主 agent / pipeline 其他节点的 LLM 上下文。强隔离是铁律
- ❌ **Agent resume** —— 不做"从中断处继续跑"的功能,CC 有我们不要
- ❌ **实时流式 chat UI 可见性** —— 运行中子 agent 的工具调用不在 chat 里滚动显示,这是 CC UI 层的事,和数据对齐无关
- ❌ **复刻 CC 消息包装格式** —— 不引入 `parentUuid / isSidechain / type:'assistant'`,沿用 `state.messages` 现有 dict 格式(`role / content / tool_calls / tool_call_id / metadata`)
- ❌ **复刻 CC 完整 usage 对象** —— 不存 `input_tokens / output_tokens / cache_creation_input_tokens / cache_read_input_tokens` 细分,只存 `total_tokens` 单个 INT(我们 telemetry 已经有细分)

## Decisions

### Decision 1:存储介质 —— PG JSONB vs 独立文件

**选 PG JSONB 列**。

- **备选 A**(CC 风格):给每个 agent run 一个独立 jsonl 文件存盘,`agent_runs` 表只存路径引用
- **备选 B**(采用):`agent_runs` 加 `messages: JSONB` 列,原地存完整消息数组

理由:

1. 我们整个项目都走 PG JSONB(`Conversation.messages` / `workflow_runs.metadata_` 等),沿用已有模式零架构新增
2. Docker compose 部署场景下,文件存储需要挂 volume,JSONB 零配置
3. 单 row 体量:子 agent 典型 20-50 条消息 × ~1 KB = 20-50 KB,PG JSONB 吃得下(PG 单行软上限 ~1 GB,TOAST 自动压缩)
4. 查询便利:`SELECT result, tool_use_count FROM agent_runs WHERE id=?` 一次 round-trip,不用先查路径再读文件
5. 级联删除自动 work(会话/run 删除时 JSONB 跟着走)

Trade-off:JSONB 列大于 8 KB 会触发 TOAST,大批量 `SELECT *` 场景有一定开销 —— 缓解方式是分析页 list 接口不返回 `messages` 列,只详情接口返回。

### Decision 2:`messages` 字段格式 —— 直接存 `state.messages` dict 列表

**选直接存,不做任何包装**。

`state.messages` 在 agent loop 里本来就是 `list[dict]`,每个 dict 是 OpenAI-compatible 的消息格式:

```python
{
    "role": "user" | "assistant" | "tool" | "system",
    "content": str | list,
    "tool_calls": [...],  # assistant role
    "tool_call_id": str,  # tool role
    "metadata": {...},     # 内部扩展
}
```

备选:复刻 CC 的 `{type: 'assistant', message: {content: [...]}, uuid, parentUuid, isSidechain, ...}` 结构。

理由拒绝 CC 结构:

1. 我们没有 `parentUuid` 链的概念(CC 需要它是因为 resume 要重建图,我们不做 resume)
2. `isSidechain` 对我们没意义 —— `agent_runs.messages` 物理上就是独立列,不需要标记
3. `type` 字段是冗余的,已经有 `role`
4. 引入 CC 格式意味着 agent_loop 内部也要改用它,或者存的时候做一次转换,都徒增复杂度

**后果**:前端抽屉组件读出来的就是 `state.messages` 原样,直接渲染。和 chat 历史加载用的 `convertHistoryMessages` 函数可以复用。

### Decision 3:三个统计字段的产生方式 —— 在 `AgentState` 里累计

**在 loop 层记账,而不是结束时扫消息统计**。

- **备选 A**(结束时扫):`complete_agent_run` 接收 `state.messages`,遍历数完 tool_calls 数量、usage 总和。简单但 O(N) 浪费,而且每个调用点都要重复这段逻辑
- **备选 B**(loop 层记账,采用):`AgentState` 加 `tool_use_count: int` 和 `cumulative_tokens: int`,`agent_loop` 每个 turn 结束时:
  ```python
  state.tool_use_count += len(tool_calls)
  state.cumulative_tokens += usage.total_tokens
  ```
- **备选 C**(telemetry 反查):通过 `current_spawn_id` 查 `agent_turn` 表汇总。重。且 telemetry 是可 opt-out 的,将来关闭 telemetry 这条路就断了

理由选 B:

1. `tool_use_count` 在 loop 本来就能自然算出(`len(tool_calls)` 是分发前已有的量)
2. `cumulative_tokens` 也已经有 `usage.total_tokens` 现成的,加一行即可
3. `duration_ms` 在调用点算(`time.monotonic()` 包住 `run_agent_to_completion`),不占 AgentState
4. 避免 agent_runs 数据依赖 telemetry opt-in

### Decision 4:`run_agent_to_completion` 返回富结构 vs 让调用点自己拿

**返回富结构**,命名 `AgentRunResult`。

```python
@dataclass
class AgentRunResult:
    exit_reason: ExitReason
    messages: list[dict]       # 引用 state.messages
    final_output: str          # 已做 extract_final_output
    tool_use_count: int
    cumulative_tokens: int
    duration_ms: int
```

- **备选 A**:保持 `run_agent_to_completion(state) -> ExitReason` 原签名,调用点自己 `state.messages / state.tool_use_count / ...` 这样拿。改动小但调用点会重复同样三行
- **备选 B**(采用):返回 `AgentRunResult`,调用点拿到直接喂给 `complete_agent_run`

理由:`spawn_agent._run_agent_background` 和 `pipeline._run_node` 拿结果后做的事完全一样(算耗时 + 调 complete_agent_run),富结构让两边对称地只写一行。DRY。

### Decision 5:`<task-notification>` XML 字段 —— 追加不改结构

```xml
<task-notification>
  <agent-run-id>123</agent-run-id>
  <role>analyst</role>
  <status>completed</status>
  <tool-use-count>5</tool-use-count>     <!-- 新增 -->
  <total-tokens>12453</total-tokens>     <!-- 新增 -->
  <duration-ms>47123</duration-ms>       <!-- 新增 -->
  <result>分析结果是…</result>
</task-notification>
```

顺序:已有字段保持原位,三个新字段插在 `<status>` 和 `<result>` 之间(逻辑上"元数据 → 结果"的自然分组)。

**失败场景**:子 agent 跑失败时 `<status>failed</status>`,统计字段仍然写(哪怕是 0)。主 agent 能看到"子 agent 跑了 3 次工具但最后失败了"。

### Decision 6:REST endpoint 设计 —— `GET /api/agent-runs/{id}`

**独立 top-level resource**,不嵌套在 `/runs/{run_id}/agent-runs/{id}` 下面。

理由:

1. `agent_runs.run_id` 既可能指向 `workflow_runs.id`(pipeline 场景),也可能指向 chat session 的 run_id 概念 —— 嵌套会让 URL 语义混乱
2. 前端两处复用同一个抽屉组件,URL 统一更简单
3. 已有 `/api/runs/{run_id}/agent-runs` 作为 list 接口(见 `src/api/runs.py:AgentRunListResponse`),新 endpoint 是详情补全,职责分离

**返回 schema**:

```json
{
  "id": 123,
  "run_id": 456,
  "role": "analyst",
  "description": "...",
  "status": "completed",
  "owner": "run-xxx:analyst",
  "result": "...",
  "messages": [...],
  "tool_use_count": 5,
  "total_tokens": 12453,
  "duration_ms": 47123,
  "created_at": "2026-04-14T...",
  "updated_at": "2026-04-14T..."
}
```

list 接口(`AgentRunItem`)**不返回** `messages` 字段,避免 TOAST 开销。

### Decision 7:前端抽屉组件复用策略

**一个组件,两个入口**:

- 组件:`web/src/components/AgentRunDetailDrawer.tsx`
- Props:`{ agentRunId: number | null; onClose: () => void }`
- 内部:fetch `GET /api/agent-runs/{id}`,渲染:
  - 顶部 metadata 条:role / status / 三个统计 badge / created_at
  - 中部:description(原始 task description)
  - 中部:messages transcript,复用 `convertHistoryMessages` 转换后交给 `@assistant-ui/react` 的只读渲染器
  - 底部:final result 文字

两个入口:

1. **Chat**:`useSessionRuntime.convertHistoryMessages` 里识别 `metadata.kind === "task_notification"` 的卡片,点击时 `setState({ drawerAgentRunId: meta.agent_run_id })`,渲染 `<AgentRunDetailDrawer agentRunId={...} />`
2. **Pipeline**:`RunDetailPage.tsx` 的节点列表(或 DAG graph 节点)点击时,根据节点 `role` + `run_id` 查 `/api/runs/{run_id}/agent-runs` list,取匹配 role 的 id,打开抽屉

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| **JSONB 列 TOAST 开销**:子 agent 消息量大时单行 > 8 KB 触发 TOAST,list 查询变慢 | list 接口不返回 `messages` 列,只详情接口返回;`AgentRunItem` Pydantic 不声明 `messages` 字段 |
| **消息 PII/敏感信息全量落盘**:原本 result 只存最终文字,现在 tool 调用参数、中间思考全存 PG | 风险可接受:PG 本来已经存完整 Conversation.messages(主会话),子 agent 走同样 DB 同样安全层,没引入新攻击面;未来做脱敏也是统一处理 |
| **`AgentRunResult` dataclass 改动破坏下游**:`run_agent_to_completion` 返回值变化,可能有未识别的调用点 | grep 全仓确认只有两个调用点(spawn_agent + pipeline),单元测试 + smoke 跑通即验证 |
| **`<task-notification>` XML 字段追加改变主 agent prompt**:主 agent 可能看到新字段后行为变化 | 新字段是纯追加,对已有 agent 指令无干扰;测试覆盖主 agent 能读到字段即可,不做 prompt-level 回归(agent 本来就是随机的) |
| **pipeline 节点 agent 的 `AgentState` 没有 tool_use_count 字段时老代码崩溃** | 在 `AgentState` 里用 `field(default=0)` 默认值,reactive 和 auto compact 路径都 safe |
| **失败 agent 的统计字段** | `fail_agent_run` 也接收统计参数,不 NULL。`format_task_notification` 的 status=failed 分支也写入 |

## Migration Plan

1. **Schema migration**:`scripts/init_db.sql` 追加四列(`ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS ...`),新实例 `init_db` 一次建好,已有实例启动时自动 idempotent 加列
2. **代码顺序**:
   1. `models.py` + `scripts/init_db.sql` 先落地 schema
   2. `AgentState` + `agent_loop` 累计字段
   3. `AgentRunResult` dataclass + `run_agent_to_completion` 返回结构
   4. `complete_agent_run` / `fail_agent_run` 签名扩展
   5. `spawn_agent` / `pipeline._run_node` 调用点升级(两处同步改)
   6. `format_task_notification` XML 字段
   7. REST endpoint
   8. 前端抽屉组件 + 两处入口
3. **回滚策略**:schema 加列向后兼容,回滚代码即可保留 PG 数据;`messages` / 三个统计列 NULL-safe,老代码读不到不崩溃
4. **数据回填**:不需要。老 agent_runs 行的 `messages = []`、统计 = 0,符合"过去没记录"的语义
