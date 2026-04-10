## 1. 依赖与基础设施

- [x] 1.1 添加 langgraph、langgraph-checkpoint-postgres 到 pyproject.toml
- [x] 1.2 在 init_db 中添加 PostgresSaver.setup() 调用，创建 checkpoint 表
- [x] 1.3 创建 checkpointer 单例（get_checkpointer），复用现有数据库连接池

## 2. PipelineState 与 YAML 扩展

- [x] 2.1 定义 PipelineState(TypedDict)：user_input, outputs(Annotated merge reducer), run_id, project_id, permission_mode
- [x] 2.2 扩展 NodeDefinition dataclass 添加 interrupt: bool = False 和 routes: list[RouteDefinition] = [] 字段
- [x] 2.3 定义 RouteDefinition dataclass：condition(str|None), target(str), is_default(bool)
- [x] 2.4 更新 load_pipeline 解析 YAML 中的 interrupt 和 routes 字段
- [x] 2.5 load_pipeline 校验：route target 引用合法节点、至多一个 default、无 default 且无全覆盖时报错

## 3. build_graph 核心实现

- [x] 3.1 创建 src/engine/graph.py，实现 build_graph(pipeline_def) → CompiledGraph
- [x] 3.2 实现 node_fn 工厂函数：闭包捕获 run_id_int/mcp_manager/abort_signal，包装 _run_node
- [x] 3.3 node_fn 中处理 Task 记录创建（create_task / complete_task / fail_task）
- [x] 3.4 node_fn 中 catch 异常写 error 到 state（不抛出）
- [x] 3.5 interrupt: true 节点自动拆成两个 LangGraph 节点（agent_run + interrupt_wait）
- [x] 3.6 每个节点后添加 conditional edge：检查 state error → 有 error 跳 END，无 error 走下游
- [x] 3.7 根据 input/output 依赖添加 edges（含 fan-out 支持）
- [x] 3.8 有 routes 的节点生成条件路由 edge：读 output 内容做 substring 匹配，命中走 target，否则走 default
- [x] 3.9 routes 条件路由与 error 检查共存：error 优先跳 END，无 error 再走 routes

## 4. execute_pipeline 改造

- [x] 4.1 重写 execute_pipeline：用 build_graph + graph.invoke 替换 while-loop 调度
- [x] 4.2 PipelineResult 新增 paused_at: str | None 字段，status 支持 'paused'
- [x] 4.3 RunStatus 枚举新增 PAUSED，状态机适配（RUNNING→PAUSED→RUNNING）
- [x] 4.4 保持 PipelineStart / PipelineEnd hook 在 graph.invoke 前后触发
- [x] 4.5 保持 MCP manager 生命周期在 graph 外层管理

## 5. resume 与状态查询

- [x] 5.1 实现 resume_pipeline(run_id, feedback)：rebuild graph + graph.invoke(Command(resume=...))
- [x] 5.2 实现 get_pipeline_status(run_id)：查 checkpoint 返回 running/paused/completed + paused_at
- [x] 5.3 resume_pipeline 中校验 run_id 对应的 checkpoint 是否存在

## 6. Gateway /resume 命令

- [x] 6.1 Gateway._process_message 中识别 /resume 前缀，分发到 _handle_resume
- [x] 6.2 实现 _handle_resume：按 project_id 查暂停 runs，显示 pipeline_name + paused_at
- [x] 6.3 处理边界情况：无暂停 run、多暂停 run 列表、指定 run_id、带 feedback

## 7. Coordinator 拆分

- [x] 7.1 run_coordinator 去掉 pipeline if 分支，只保留自主模式
- [x] 7.2 CoordinatorResult 去掉 mode='pipeline' 和 node_outputs 字段
- [x] 7.3 调用方（CLI / 测试脚本）直接判断 pipeline → execute_pipeline / 无 pipeline → run_coordinator

## 8. 测试 — 单元测试

- [x] 8.1 test_pipeline_state.py：PipelineState 初始化、outputs merge reducer 验证
- [x] 8.2 test_build_graph.py：线性图、fan-out 图、单节点图的构建验证
- [x] 8.3 test_node_fn.py：entry node 收到 user_input、非 entry node 收到上游 outputs、Task 记录创建
- [x] 8.4 test_build_graph.py：interrupt 节点拆分验证（reviewer_run + reviewer_interrupt 节点存在）
- [x] 8.5 test_resume_pipeline.py：正常 resume、无 checkpoint 报错、带 feedback resume（mock）
- [x] 8.6 test_pipeline_status.py：running/paused/completed 状态查询（mock）
- [x] 8.7 test_yaml_interrupt.py：YAML interrupt 字段解析、默认值、NodeDefinition 扩展
- [x] 8.8 test_error_handling.py：节点失败 → error 写入 state → conditional edge 跳 END → 下游不执行
- [x] 8.9 test_conditional_routing.py：condition 匹配走对应 target、不匹配走 default、无 default 报错
- [x] 8.10 test_conditional_routing.py：error 优先于 routes（节点失败时不走 routes，直接 END）
- [x] 8.11 test_yaml_routes.py：routes 字段解析、RouteDefinition 构建、target 校验、default 校验

## 9. 测试 — 路径隔离

- [x] 9.1 test_path_isolation.py：pipeline 执行不触发 coordinator_loop
- [x] 9.2 test_path_isolation.py：pipeline 执行不触发 gateway._run_agent
- [x] 9.3 test_path_isolation.py：gateway 聊天不触发 execute_pipeline
- [x] 9.4 test_path_isolation.py：/resume 命令不触发 coordinator_loop
- [x] 9.5 test_path_isolation.py：/resume 命令不创建 chat agent
- [x] 9.6 test_path_isolation.py：coordinator spawn_agent 不触发 execute_pipeline

## 10. 测试 — 集成测试

- [x] 10.1 test_integration_interrupt.py：完整 pipeline 执行 → interrupt → resume → 完成的端到端流程（MemorySaver mock）
- [x] 10.2 test_integration_interrupt.py：多节点 pipeline 中间 interrupt 后 resume，验证上下游 outputs 传递正确（MemorySaver mock）
- [x] 10.3 test_execute_pipeline_compat.py：验证改造后的 execute_pipeline 对无 interrupt 的 pipeline 行为与改造前一致（MemorySaver mock）
- [x] 10.4 test_coordinator_split.py：验证 run_coordinator 只做自主模式，pipeline 路由由调用方处理（mock）
