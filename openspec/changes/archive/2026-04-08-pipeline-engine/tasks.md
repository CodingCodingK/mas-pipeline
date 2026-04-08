## 1. 管线定义与加载

- [x] 1.1 定义 NodeDefinition 和 PipelineDefinition dataclass
- [x] 1.2 实现 load_pipeline(yaml_path)：解析 YAML、构建 output_to_node 映射、推导 dependencies
- [x] 1.3 实现校验：output 唯一性、input 引用合法性、无环检测（Kahn 算法）
- [x] 1.4 创建 pipelines/ 目录，编写一个测试用 YAML 管线定义

## 2. 调度引擎核心

- [x] 2.1 定义 PipelineResult dataclass（run_id, status, outputs, final_output, failed_node, error）
- [x] 2.2 实现 execute_pipeline(pipeline_name, run_id, project_id, user_input) 主函数框架：加载管线、初始化状态、WorkflowRun 状态更新
- [x] 2.3 实现 reactive 调度循环：pending/running/completed 集合、就绪检测、asyncio.wait(FIRST_COMPLETED)
- [x] 2.4 实现节点执行函数：create_agent + agent_loop + extract_final_output + Task 记录创建与更新

## 3. 数据传递与错误处理

- [x] 3.1 实现入口节点 task_description 组装（直接使用 user_input）
- [x] 3.2 实现非入口节点 task_description 组装（拼接上游 output 为标记分隔文本块）
- [x] 3.3 实现失败节点下游级联 skipped 标记
- [x] 3.4 实现 abort_signal 共享：管线级 Event 实例传递给所有子 Agent

## 4. 验证

- [x] 4.1 编写 scripts/test_pipeline_engine.py：加载 YAML + 依赖推导 + 校验测试
- [x] 4.2 补充调度循环测试：MockAdapter 驱动，验证并行启动和就绪检测
