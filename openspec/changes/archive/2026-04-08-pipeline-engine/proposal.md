## Why

Phase 2 的 subagent 和 workflow-run 已就绪，但目前只能通过 `spawn_agent` 手动逐个启动子 Agent。缺少一个系统级调度器，根据预定义的 YAML 管线自动编排多个 Agent 的执行顺序、并行策略和数据流转。Pipeline Engine 是 Coordinator（2.8）和 Blog Pipeline（2.9）的前置依赖。

## What Changes

- 新增 YAML 管线定义格式：每个管线由 `nodes` 列表组成，节点只有 `name`/`role`/`input`/`output` 四个字段，依赖关系从 input/output 自动推导，无 edges
- 新增管线加载器：解析 YAML、构建依赖图、校验（output 唯一、input 引用合法、无环检测）
- 新增 reactive 调度引擎：就绪即启动模式，节点所有上游 output 到齐立即启动，`asyncio.wait(FIRST_COMPLETED)` 驱动
- 每个节点统一走 `create_agent` + `agent_loop`，上游输出注入下游 `task_description`
- Engine 只接收 `run_id`（由上层创建 WorkflowRun），负责执行和状态更新
- 返回 `PipelineResult`，包含所有中间节点输出

## Capabilities

### New Capabilities
- `pipeline-definition`: YAML 管线定义格式、加载、依赖推导、校验
- `pipeline-execution`: reactive 调度引擎、节点执行、数据传递、错误处理

### Modified Capabilities
- `pipeline-run`: WorkflowRun 增加 pipeline 字段的使用语义——Engine 执行时更新 run 状态（pending→running→completed/failed）

## Impact

- 新增文件：`src/engine/pipeline.py`（替换当前空文件）
- 新增目录：`pipelines/`（存放 YAML 管线定义文件）
- 依赖模块：`src/agent/factory.py`（create_agent）、`src/agent/loop.py`（agent_loop）、`src/engine/run.py`（run 状态管理）、`src/task/manager.py`（Task 跟踪）
- 无新外部依赖，PyYAML 已在项目中
