## 1. CoordinatorResult 数据结构

- [x] 1.1 在 `src/engine/coordinator.py` 中定义 CoordinatorResult dataclass（run_id, mode, output, node_outputs, agent_runs）

## 2. coordinator_loop 外层循环

- [x] 2.1 实现 `coordinator_loop(state)` — 初始化 notification_queue + running_agent_count → 外层 while True：调 agent_loop → count==0 则 break → await queue.get() + drain → 注入 messages → 重入
- [x] 2.2 notification 注入逻辑：从 queue 取出 notification dict，将 message 字段 append 为 user message

## 3. run_coordinator 路由函数

- [x] 3.1 实现 `run_coordinator(project_id, user_input)` — 创建 WorkflowRun → 查 Project.pipeline → 有匹配则 execute_pipeline → 无则 coordinator_loop
- [x] 3.2 管线模式路径：调用 execute_pipeline，将 PipelineResult 转换为 CoordinatorResult
- [x] 3.3 自主模式路径：创建 Coordinator Agent（role="coordinator"，notification_queue 已由 coordinator_loop 初始化），提取最终输出 + list_agent_runs 查审计记录
- [x] 3.4 错误处理：执行失败时 finish_run(FAILED)，成功时 finish_run(COMPLETED)

## 4. Coordinator 角色文件

- [x] 4.1 编写 `agents/coordinator.md`：frontmatter（tools: [spawn_agent], model_tier: heavy）+ 角色定义 + 工具说明 + notification 机制说明 + 任务工作流 + 并行策略 + prompt 编写指南 + 汇总策略

## 5. 验证

- [x] 5.1 编写 `scripts/test_coordinator.py` — 单元测试：CoordinatorResult 构建、路由逻辑（mock Pipeline/Agent）
- [x] 5.2 编写 `scripts/test_coordinator_loop.py` — coordinator_loop 测试：mock agent_loop + 模拟 notification queue push，验证 notification 注入和重入逻辑
