## Why

当前 `execute_pipeline` 用 while-loop + asyncio.wait 做节点调度，一旦启动就只能跑到底或失败。没有暂停/恢复能力，也无法在运行中途查看快照或回溯。业务上需要在特定节点执行完后暂停（如人工审核），通过显式命令恢复；也需要在出错时从某个快照恢复，而不是从头重跑整条 pipeline。

## What Changes

- 引入 LangGraph StateGraph 替换 `execute_pipeline` 内部的 while-loop 调度逻辑
- 每个 pipeline node 包装为一个 LangGraph 节点函数，内部仍调用 `create_agent` + `run_agent_to_completion`（不改 agent 系统）
- 引入 PostgresSaver 做 checkpoint 持久化，与现有 workflow_runs / agent_runs 表共存（通过 run_id = thread_id 关联）
- YAML pipeline 配置扩展 `interrupt: true` 字段，标记需要暂停的节点
- Gateway 新增 `/resume` 命令入口，查询暂停的 run 并调用 `resume_pipeline()`
- 新增 `get_pipeline_status()` 查询 pipeline 快照状态

## Capabilities

### New Capabilities
- `langgraph-engine`: LangGraph StateGraph 构建（build_graph）、节点函数包装、PipelineState 管理
- `pipeline-interrupt`: interrupt/resume 机制 — YAML interrupt 配置、interrupt() 调用、Command(resume=feedback) 恢复
- `pipeline-checkpoint`: PostgresSaver checkpoint 持久化、快照查询、run_id↔thread_id 关联
- `gateway-resume`: Gateway `/resume` 命令解析、暂停 run 查询、resume 路由

### Modified Capabilities
- `pipeline-execution`: execute_pipeline 内部调度从 while-loop 改为 LangGraph StateGraph.invoke，函数签名和返回值不变
- `pipeline-definition`: YAML node 新增可选 `interrupt: true` 字段和 `routes` 条件路由字段
- `coordinator-routing`: run_coordinator 去掉 pipeline 透传分支，只做自主模式，路由上移调用方

## Impact

- **代码**: `src/engine/pipeline.py` 重写调度逻辑；新增 `src/engine/graph.py`（build_graph、node_fn）；`src/bus/gateway.py` 新增 /resume 处理
- **数据库**: 新增 LangGraph PostgresSaver 所需的 4 张 checkpoint 表（由 PostgresSaver.setup() 自动创建）
- **依赖**: 新增 `langgraph`、`langgraph-checkpoint-postgres` 包
- **YAML**: pipeline YAML node 新增可选 `interrupt` 字段（默认 false）和 `routes` 条件路由字段（默认无），均向后兼容
- **不受影响**: agent 系统（create_agent / agent_loop）、Coordinator 自主模式、Gateway 聊天模式 — 三条路径完全隔离
