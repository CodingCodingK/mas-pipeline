## 1. PipelineRun 最小实现

- [ ] 1.1 在 `src/models.py` 增加 PipelineRun ORM model（匹配 pipeline_runs 表）
- [ ] 1.2 实现 `src/engine/run.py` — create_run(project_id) 插入记录并返回 PipelineRun

## 2. 全局工具池

- [ ] 2.1 实现 `src/tools/builtins/__init__.py` — get_all_tools() 返回所有内置工具实例 + AGENT_DISALLOWED_TOOLS 禁用列表

## 3. Agent 工厂

- [ ] 3.1 实现 `src/agent/factory.py` — create_agent 函数：解析 role 文件 → 路由 adapter → 过滤工具 → 构建 AgentState

## 4. SpawnAgent 工具

- [ ] 4.1 实现 `src/tools/builtins/spawn_agent.py` — SpawnAgentTool + extract_final_output
- [ ] 4.2 在 get_all_tools() 中注册 spawn_agent

## 5. Task 工具集

- [ ] 5.1 实现 `src/tools/builtins/task.py` — TaskCreateTool / TaskUpdateTool / TaskListTool / TaskGetTool
- [ ] 5.2 在 get_all_tools() 中注册 task_create / task_update / task_list / task_get

## 6. 验证

- [ ] 6.1 创建 `scripts/test_subagent.py` — 验证：create_agent 构建 AgentState → spawn_agent 后台执行 → task_list 查看状态 → task_get 取回结果
