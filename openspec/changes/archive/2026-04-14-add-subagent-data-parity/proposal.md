## Why

子 agent(chat 场景的 `spawn_agent` 派生、pipeline 节点执行的 agent)跑完后只把"最后一条 assistant 文字"写进 `agent_runs.result`,完整消息流、工具调用、token 消耗全部丢弃。结果:调试出错的子 agent 没有证据链,分析页看不到过程,主 agent 也拿不到"子 agent 花了多少资源"这类统计(无法做 cost-aware 决策)。CC 的对齐做法是把子 agent transcript 独立持久化(sidechain jsonl),同时把统计字段随返回结果一起回传主 agent。本 change 把同样的**数据**对齐搬到 PG 里,**不做**实时流式 UI 对齐,不破坏主 agent 和子 agent 之间的强隔离。

## What Changes

- `agent_runs` 表扩展:新增 `messages JSONB`、`tool_use_count INT`、`total_tokens INT`、`duration_ms INT` 四列,schema migration 写入 `scripts/init_db.sql`
- `complete_agent_run` / `fail_agent_run` 签名扩展:新增 `messages` / `tool_use_count` / `total_tokens` / `duration_ms` 参数,写入新列
- `run_agent_to_completion` 语义扩展:返回值改为富结构(含 `messages`、`tool_use_count`、`total_tokens`、`duration_ms`、`exit_reason`),让调用点无需自己汇总
- `AgentState` 扩展:新增 `tool_use_count`、`cumulative_tokens` 字段,`agent_loop` 在每个 turn 结束时累计
- `spawn_agent._run_agent_background` 改造:结束时把富结构写入 `complete_agent_run`;`format_task_notification` XML 追加 `<tool-use-count>`、`<total-tokens>`、`<duration-ms>` 三个字段
- `src/engine/pipeline.py:_run_node` 改造:结束时同样写入富结构
- **新 REST**:`GET /api/agent-runs/{id}` 返回完整 `{id, run_id, role, status, result, messages, tool_use_count, total_tokens, duration_ms, created_at, updated_at}`
- **前端**:新建 `AgentRunDetailDrawer` 组件,chat 的 task_notification 卡片点击进详情,pipeline RunDetailPage 的节点点击进详情,两处复用同一个抽屉
- **BREAKING**:`complete_agent_run` / `fail_agent_run` / `run_agent_to_completion` 签名变化。内部调用点统一升级,没有对外 API 契约变化
- **铁律(不做的事)**:主 agent 的 LLM 上下文绝对不注入 `agent_runs.messages`;不做 agent resume;不做实时流式 chat UI 子 agent 可见;不复刻 CC 的 `parentUuid / isSidechain` 消息包装,沿用现有 `state.messages` dict 格式;不复刻 CC 完整 `usage` 细分

## Capabilities

### New Capabilities

*(无新能力,全部是对现有能力的扩展)*

### Modified Capabilities

- `agent-run-lifecycle`: `agent_runs` schema 扩展 + `complete_agent_run` / `fail_agent_run` 签名扩展
- `agent-loop`: `run_agent_to_completion` 返回富结构,`AgentState` 累计 `tool_use_count` / `cumulative_tokens`
- `spawn-agent`: 结束时写入完整 transcript + 统计;`<task-notification>` XML 追加三个统计字段
- `pipeline-execution`: pipeline 节点 agent 结束时写入完整 transcript + 统计
- `rest-api`: 新增 `GET /api/agent-runs/{id}` endpoint
- `chat-ui`: `task_notification` 卡片点击唤起 agent run 详情抽屉
- `pipeline-run`: `RunDetailPage` 节点点击唤起 agent run 详情抽屉(复用同一抽屉组件)

## Impact

- **Schema**:`agent_runs` 新增四列,需要 `ALTER TABLE` migration。现有行 `messages` 默认 `[]`、三个统计列默认 `0`,向后兼容。
- **代码**:
  - `src/models.py`:`AgentRun` ORM 扩展
  - `src/agent/runs.py`:`complete_agent_run` / `fail_agent_run` 签名
  - `src/agent/state.py`:`AgentState` 字段
  - `src/agent/loop.py`:turn 级累计 + `run_agent_to_completion` 返回富结构
  - `src/tools/builtins/spawn_agent.py`:调用点升级 + XML 字段补全
  - `src/engine/pipeline.py`:调用点升级
  - `src/api/runs.py`:新 endpoint
  - `web/src/components/AgentRunDetailDrawer.tsx`:新建
  - `web/src/pages/ChatPage.tsx` / `useSessionRuntime.ts`:task_notification 卡片点击入口
  - `web/src/pages/RunDetailPage.tsx`:节点点击入口
- **测试**:新增 `scripts/test_agent_run_persistence.py`(后端持久化 + REST);现有 `test_spawn_agent.py` / `test_pipeline_*.py` 断言扩展字段
- **向后兼容**:对外 REST API 无破坏性变化,`AgentRunItem` 已有字段保持不变,新 endpoint 是纯新增。内部函数签名变化是内部契约,一次性升级。
- **性能**:子 agent 典型 20-50 条消息,JSONB 约 20-50 KB/行。1 万次 run = 200-500 MB,PG 毫无压力。
