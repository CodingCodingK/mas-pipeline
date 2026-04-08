## Why

Phase 2 需要多 Agent 协作。Coordinator 要能派出专业子 Agent（researcher / writer / reviewer）执行具体任务，并跟踪它们的状态和结果。当前只有单 Agent 循环（Phase 1），没有 Agent 创建和 spawn 能力。

业务场景：
- 自主模式：Coordinator 用 task_create 规划工作，用 spawn_agent 派子 Agent 异步执行，用 task_list/task_get 轮询状态和取结果
- 管线模式（2.7）：Pipeline Engine 调 create_agent + agent_loop 按拓扑序执行节点

## What Changes

- 新增 `src/engine/run.py` — 最小 PipelineRun 创建（给 Task 提供合法 run_id 外键）
- 新增 `src/tools/builtins/__init__.py` — 全局工具池 + 子 Agent 禁用列表
- 新增 `src/agent/factory.py` — Agent 工厂函数，从 role 文件创建独立 AgentState
- 新增 `src/tools/builtins/spawn_agent.py` — 异步后台 spawn 子 Agent 工具
- 新增 `src/tools/builtins/task.py` — Task 工具集（create/update/list/get）给 LLM 使用
- 修改 `src/models.py` — 新增 PipelineRun ORM model

## Capabilities

### New Capabilities
- `agent-factory`: 从 role 文件创建独立 AgentState（独立 messages、tools、adapter）
- `spawn-agent`: 异步后台启动子 Agent，自动创建 Task 跟踪，立即返回 task_id
- `task-tools`: LLM 可用的 Task 工具集（规划 + 查询，与 spawn 解耦）
- `pipeline-run`: 最小 PipelineRun 创建

### Modified Capabilities
（无）

## Impact

- 新增文件：`src/engine/run.py`, `src/agent/factory.py`, `src/tools/builtins/spawn_agent.py`, `src/tools/builtins/task.py`
- 修改文件：`src/models.py`（增加 PipelineRun model）, `src/tools/builtins/__init__.py`（全局工具池）
- 数据库：`pipeline_runs` 表已在 Phase 0 建好
- 下游：Coordinator（2.8）消费 spawn_agent + task tools，Pipeline Engine（2.7）消费 create_agent
