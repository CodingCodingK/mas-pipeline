## Why

Pipeline Engine (Phase 2.7) 实现了系统级的 YAML 管线调度，但缺少统一入口。用户输入到达后，需要一个路由层决定走管线模式还是自主模式。自主模式是 mas-pipeline 项目的核心——真正的多 Agent 系统需要 Coordinator 进行 LLM 驱动的任务拆解、派发、等待和汇总。

## What Changes

- 新增 `run_coordinator()` 路由函数：根据 Project.pipeline 字段决定模式
- 新增 `coordinator_loop()`：CC 风格的 do-while 外层循环，通过 asyncio.Queue 通知队列等待子 Agent 完成并重入
- 新增 `CoordinatorResult` dataclass：统一两种模式的返回结构
- 新增 `agents/coordinator.md` 角色文件：参考 CC coordinatorMode.ts 裁剪的协调者 prompt
- Coordinator 唯一工具：spawn_agent（无执行工具，无 task_* 工具）

## Capabilities

### New Capabilities
- `coordinator-routing`: 路由函数，根据 project 配置分发到管线模式或自主模式
- `coordinator-loop`: 外层 do-while 循环 + asyncio.Queue 通知队列，管理子 Agent 完成通知注入
- `coordinator-role`: Coordinator Agent 角色定义和 prompt 设计

### Modified Capabilities
- `pipeline-run`: create_run 调用移入 run_coordinator，由 Coordinator 统一创建 WorkflowRun

## Impact

- 新增 `src/engine/coordinator.py` — 路由函数 + coordinator_loop + CoordinatorResult
- 新增 `agents/coordinator.md` — 协调者角色 prompt
- 依赖 `src/engine/pipeline.py`（管线模式调用 execute_pipeline）
- 依赖 `src/agent/loop.py`（自主模式调用 agent_loop）
- 依赖 `src/agent/factory.py`（创建 Coordinator Agent）
- 依赖 `src/engine/run.py`（WorkflowRun 生命周期管理）
- 依赖 `src/agent/runs.py`（AgentRun 审计记录，仅用于 CoordinatorResult 返回）
