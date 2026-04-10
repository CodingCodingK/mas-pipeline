## Context

当前 `execute_pipeline()` 用 while-loop + `asyncio.wait(FIRST_COMPLETED)` 做响应式调度。节点执行逻辑是 `create_agent → run_agent_to_completion → extract_final_output`。这套调度没有持久化中间状态的能力——一旦进程退出，所有中间结果丢失，无法恢复。

系统有三条独立执行路径：
1. **Pipeline 路径**: `execute_pipeline → _run_node → create_agent` — 本次改造对象
2. **Coordinator 路径**: `coordinator_loop → spawn_agent → create_agent` — 不动（但拆掉 pipeline 透传分支）
3. **Gateway 路径**: Discord/QQ/WeChat → `gateway._run_agent → create_agent` — 只加 `/resume` 命令入口

## Goals / Non-Goals

**Goals:**
- 用 LangGraph StateGraph 替换 execute_pipeline 内部的 while-loop 调度
- 支持 `interrupt: true` 配置的节点在执行完后暂停，等待显式 `/resume` 恢复
- 用 PostgresSaver 持久化 checkpoint，支持快照查询和回溯
- Gateway 新增 `/resume` 命令，路由到对应的暂停 pipeline
- Coordinator 拆分：去掉 pipeline 透传分支，路由上移调用方
- 确保三条路径完全隔离，pipeline 改造不影响 coordinator 和 gateway 聊天

**Non-Goals:**
- 不引入 WorkflowTool 或任何 agent 自主触发 pipeline 的机制
- 不改 agent 系统（create_agent / agent_loop / run_agent_to_completion）
- 不改 Coordinator 自主模式的调度逻辑
- 不做意图检测——resume 只通过显式 `/resume` 命令触发
- 不做复杂条件表达式引擎（如 eval / DSL）——条件路由用 LLM 判断或简单关键词匹配
- 不做运行中崩溃自动恢复——只保证 interrupt 暂停后的跨进程 resume

## Decisions

### 1. LangGraph 替换 while-loop，不替换整个 engine

**选择**: 只替换 `execute_pipeline` 内部的调度 while-loop，保留 `_run_node` 内部逻辑不变。

**替代方案**: 把每个 agent 也交给 LangGraph 管理（LangGraph 管 agent_loop）。

**理由**: agent 系统已经稳定运行，把 agent_loop 交给 LangGraph 管理会增加耦合，且 agent 内部的 tool-call 循环和 LangGraph 的节点模型不匹配。保持 LangGraph 只管节点调度，agent 系统保持独立。

### 2. PipelineState(TypedDict) 作为图状态

```python
class PipelineState(TypedDict):
    user_input: str
    outputs: Annotated[dict[str, str], merge_dicts]  # merge reducer 防并行覆盖
    run_id: str
    project_id: int
    permission_mode: str
```

每个节点函数读 `state["outputs"]` 获取上游输出，写回自己的 output 到 `state["outputs"]`。

**outputs 需要 merge reducer**：LangGraph 并行节点各自返回 state 更新，默认后到覆盖先到。加 reducer 保证 dict 合并不丢数据。

**不进 state 的东西（通过闭包捕获）**：hook_runner、mcp_manager、abort_signal、run_id_int——这些是 Python 对象或 asyncio 对象，无法 JSON 序列化到 checkpoint。

### 3. build_graph() 动态构建 StateGraph

从 PipelineDefinition 动态构建图：
- 每个 YAML node → 一个或两个 LangGraph 节点（见 Decision 5）
- 节点之间的 edge 由 `input/output` 依赖推导
- 失败处理用 conditional edge（见 Decision 6）

**替代方案**: 手写固定的图结构。

**理由**: pipeline YAML 是动态的，必须动态构建图。

### 4. PostgresSaver 与现有表共存

**选择**: LangGraph 用 PostgresSaver 管自己的 4 张 checkpoint 表，我们的 workflow_runs / agent_runs 保持不变。通过 `run_id = thread_id` 关联。

**替代方案**: 自己实现 checkpoint 存储，不用 PostgresSaver。

**理由**: PostgresSaver 是 LangGraph 生态的标准方案，自己实现 checkpoint 序列化/反序列化成本高且容易出错。4 张表的开销可以接受。checkpoint 持久化在 PG 中，进程重启后 resume 可以从 PG 读 checkpoint 恢复——这是 interrupt/resume 跨进程工作的基础。

### 5. interrupt 拆成两个节点（避免 resume 重跑 agent）

**问题**: LangGraph resume 时会从头重跑整个 node_fn。如果 interrupt() 和 agent 执行在同一个函数里，resume 会重跑 agent。

**解决**: `interrupt: true` 的节点在 build_graph 时自动拆成两个 LangGraph 节点：

```
editor_run  →  editor_interrupt  →  下游节点
（跑 agent）    （调 interrupt()）
```

- `editor_run`：调 _run_node，写 output 到 state，正常返回
- `editor_interrupt`：只调 interrupt()，暂停等待 resume。resume 时重跑这个轻量函数，不重跑 agent

用户 YAML 不需要改，build_graph 内部自动拆。LangGraph 官方推荐的方式就是把昂贵操作和 interrupt 放在不同节点。

### 6. 节点失败用 conditional edge

**问题**: LangGraph 没有内置 skip-downstream。节点抛异常会导致整个 graph 失败。

**解决**: node_fn 内 catch 异常 → 写 error 到 state → 每个节点后面加 conditional edge → 检查 error → 有 error 跳 END，没 error 走下游。

效果和现有 `_mark_downstream_skipped` BFS 等价，表达方式从命令式变声明式。

### 7. Gateway `/resume` 命令 — 显式入口

Gateway 在收到消息时检查是否以 `/resume` 开头：
- `/resume` → 按 project_id 查所有 status=paused 的 workflow_runs
- 显示 pipeline_name + paused_at 节点名，让用户选择
- 单个暂停 run → 直接恢复
- `/resume <run_id>` → 恢复指定 run

不做意图检测，只认 `/resume` 前缀。

### 8. PipelineResult 扩展 + RunStatus.PAUSED

PipelineResult 新增 `paused_at: str | None` 字段。status 新增 `'paused'` 值。RunStatus 枚举新增 PAUSED。状态机：RUNNING → PAUSED → RUNNING → COMPLETED/FAILED。

### 9. Coordinator 拆分

**问题**: `run_coordinator` 的 pipeline 分支只是透传调 execute_pipeline，Coordinator 没做任何决策。pipeline 模式不需要 Coordinator 的任何能力。

**解决**: 去掉 `run_coordinator` 的 pipeline 分支，路由上移到调用方。run_coordinator 只做自主模式。

```
改造后：  调用方 → { 有 pipeline → execute_pipeline（直接调）
                  { 无 pipeline → run_coordinator → coordinator_loop
```

CoordinatorResult 去掉 `mode='pipeline'` 和 `node_outputs` 字段（pipeline 结果由调用方直接从 PipelineResult 读）。

### 10. YAML 条件路由（Conditional Routing）

支持在 YAML 中定义条件分支：一个节点的输出内容决定下游走哪条路。

**YAML 语法**：节点新增可选 `routes` 字段，替代原来的固定下游：

```yaml
nodes:
  - name: reviewer
    role: reviewer
    input: [draft]
    output: review_result
    routes:
      - condition: "通过"
        target: publish
      - condition: "不通过"
        target: revise
      - default: revise        # 都不匹配时的兜底

  - name: publish
    role: publisher
    input: [review_result]
    output: published

  - name: revise
    role: writer
    input: [review_result, draft]
    output: revised_draft
```

**condition 匹配方式**：检查节点 output 内容是否包含 condition 字符串（简单 `in` 关键词匹配）。不做 eval、不做 DSL、不用 LLM 判断——保持 pipeline 执行确定性。

**build_graph 实现**：有 `routes` 的节点 → 添加 conditional edge，路由函数读 `state["outputs"][output_name]`，逐个检查 condition 是否命中，命中走对应 target，都不命中走 default。

**与 error conditional edge 共存**：error 检查优先。节点失败 → 跳 END（不走 routes）。节点成功 → 走 routes 逻辑。

## Risks / Trade-offs

**[LangGraph 版本锁定]** → 锁定 langgraph 和 langgraph-checkpoint-postgres 的 minor 版本，避免 breaking change。

**[PostgresSaver 表迁移]** → PostgresSaver.setup() 自动建表，但未来升级可能需要手动迁移。→ 记录当前使用的 langgraph 版本。

**[三条路径隔离风险]** → pipeline 改造可能意外影响 coordinator 或 gateway。→ 增加路径隔离测试（6 方向）。

**[并行节点调度]** → LangGraph StateGraph 原生支持扇出（fan-out）。需要验证并行行为与现有 asyncio.wait 一致。outputs dict 用 merge reducer 保证不丢数据。

**[断线恢复不在本期]** → 进程在节点执行中途崩溃的场景不处理。需要启动时扫描 status=running 的 runs，留待后续。
