## Context

Phase 2 已完成 subagent（agent 工厂 + spawn_agent）和 workflow-run（状态机 + Redis 同步）。目前只能通过 `spawn_agent` 工具逐个手动启动子 Agent，缺少系统级编排能力。

现有基础设施：
- `src/agent/factory.py` — `create_agent(role, task_description, ...)` 从 role 文件创建 AgentState
- `src/agent/loop.py` — `agent_loop(state)` 执行 ReAct 循环
- `src/tools/builtins/spawn_agent.py` — `extract_final_output(messages)` 提取最终输出
- `src/engine/run.py` — WorkflowRun CRUD + 状态机 + Redis 同步
- `src/task/manager.py` — Task 创建/认领/完成/失败
- `agents/*.md` — role 文件（frontmatter 定义 model_tier、tools）

## Goals / Non-Goals

**Goals:**
- YAML 管线定义格式：声明式描述多 Agent 编排
- 管线加载器：解析、依赖推导、校验
- Reactive 调度引擎：就绪即启动、最大化并行
- 节点执行：统一走 create_agent + agent_loop
- 节点间数据传递：上游输出注入下游 task_description
- PipelineResult：包含所有中间节点输出

**Non-Goals:**
- Coordinator 入口调度（Phase 2.8）
- `interrupt` 节点 / 人工审批（Phase 5 LangGraph）
- 流式输出（Phase 5 streaming）
- 节点重试 / 断点续跑（后续增量加）
- Agent 角色文件编写（Phase 2.9 Blog Pipeline）

## Decisions

### D1: YAML 格式——只用 nodes，无 edges

**选择**：节点声明 `input`（依赖的上游 output 名列表）和 `output`（本节点输出名），依赖关系自动推导。不需要 edges 区域。

**替代方案**：
- nodes + edges 双声明：edges 和 input 有信息冗余，可能矛盾
- 只用 edges：节点不知道自己需要什么输入，数据传递逻辑散落在 edges 里

**理由**：一个事实只说一次。依赖关系隐含在"我需要谁的输出"这个语义里。

### D2: 节点字段——最小化，能力跟 role 文件走

**选择**：节点只有 4 个字段：`name`、`role`、`input`（可选）、`output`。工具和模型从 `agents/{role}.md` 的 frontmatter 读取。

**替代方案**：YAML 节点中声明 tools/model_tier 作为覆盖项。

**理由**：角色能力应该跟角色走。如果同一角色在不同管线需要不同工具，创建不同 role 文件更清晰。

### D3: 所有节点统一当 Agent 跑

**选择**：不区分 agent/transform 节点类型。所有节点都走 `create_agent` + `agent_loop`。

**替代方案**：`agent: false` 节点走单次 LLM 调用。

**理由**：agent_loop 对 1 轮完成的任务几乎无额外开销（LLM 不返回 tool_call → 循环立刻退出）。统一模型消除 Engine 中的 if/else 分支。

### D4: Reactive 调度——就绪即启动

**选择**：不分层，维护 pending/running/completed 三个集合。每次有节点完成，扫描 pending 找到所有上游 output 已到齐的节点，立即启动。`asyncio.wait(return_when=FIRST_COMPLETED)` 驱动循环。

**替代方案**：
- 分层 asyncio.gather：简单但不相关的慢节点会阻塞无依赖的下游
- 全部串行：最简单但浪费并行机会

**理由**：reactive 模式比分层并行更高效，代码多约 20 行但调度效率在复杂管线下显著更好。

### D5: 数据传递——注入 task_description

**选择**：
- 入口节点（无 input）：task_description = user_input
- 非入口节点：拼接上游 output 到 task_description，格式为标记分隔的文本块

**替代方案**：
- 写文件让下游 read_file：增加工具依赖和 LLM 决策负担
- 存 DB 用专用工具读：过度工程

**理由**：博客场景下中间输出通常几千字，LLM context window 装得下。最简单，一行拼接就实现。

### D6: Engine 只接收 run_id

**选择**：`execute_pipeline(pipeline_name, run_id, project_id, user_input)` — Engine 不创建 WorkflowRun，由上层（Coordinator / API / 测试脚本）负责创建。Engine 负责 pending→running→completed/failed 的状态流转。

**理由**：WorkflowRun 语义上属于用户发起的执行请求，Engine 是执行者不是发起者。

### D7: 依赖推导与校验

加载 YAML 后执行三步校验：
1. output 名全局唯一（两个节点不能声明同一个 output）
2. input 引用合法（每个 input 名必须在某个节点的 output 中存在）
3. 无环检测（Kahn 算法，消不完说明有环）

依赖推导：扫描 `output_name → node_name` 映射，每个节点的 input 列表翻译为依赖的节点集合。

### D8: 错误处理

节点失败时：标记该节点 failed，扫描所有依赖链上的下游节点标记为 skipped，不影响无关分支继续执行。管线最终 status 为 failed，PipelineResult 记录 failed_node 和 error。

## Risks / Trade-offs

- **[上游输出过长]** → 如果某个节点输出超过 LLM context 限制，注入 task_description 会失败。Phase 3 compact 可以缓解。Phase 2 暂不处理——博客场景下不太可能出现。
- **[节点超时]** → 当前 agent_loop 有 max_turns 上限但无时间上限。Phase 2 依赖 max_turns 控制，后续可加 timeout 参数。
- **[abort 传播]** → Engine 需要在管线级别共享 abort_signal，所有子 Agent 共享同一个 Event 实例，与 subagent 设计一致。
