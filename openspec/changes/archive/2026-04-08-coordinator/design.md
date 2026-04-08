## Context

Pipeline Engine 已实现 YAML 驱动的管线调度（reactive 模式），SubAgent 机制已支持 fire-and-forget 子 Agent 派发。现在需要 Coordinator 层作为统一入口，提供两种工作模式：

1. **管线模式**：Project 配置了 pipeline 字段 → 直接调用 execute_pipeline，纯系统调度
2. **自主模式**：无匹配管线 → Coordinator Agent 用 LLM 自主拆任务、spawn 子 Agent、等待完成、汇总结果

关键参考：CC 的 coordinator 模式用 do-while + commandQueue（内存通知队列）实现子 Agent 完成通知，等待期间零 LLM 消耗。

## Goals / Non-Goals

**Goals:**
- 统一入口函数 `run_coordinator()`，一个调用覆盖两种模式
- coordinator_loop 实现外层等待循环，通过 asyncio.Queue 接收子 Agent 通知
- Coordinator Agent 角色 prompt 参考 CC coordinatorMode.ts 裁剪
- CoordinatorResult 统一返回结构

**Non-Goals:**
- 不实现 SendMessage（Phase 5.6 Event Bus）
- 不修改 agent_loop 内部逻辑
- 不实现管线自动匹配（用 Project.pipeline 精确匹配）
- 不实现 Coordinator 的执行工具（read_file / shell / write_file）

## Decisions

### D1: Coordinator 是路由函数，不是 Agent

`run_coordinator(project_id, user_input)` 是普通 Python async 函数。用 if/else 判断 Project.pipeline 字段：
- 有值 → `execute_pipeline()` 管线模式
- 无值 / None → `coordinator_loop()` 自主模式

**为什么不用 Agent 做路由**：管线模式不需要 LLM 判断，if/else 足够。省一次 LLM 调用，零延迟。

### D2: coordinator_loop 通知队列驱动（对齐 CC commandQueue）

```
coordinator_loop(state):
    state.notification_queue = asyncio.Queue()
    state.running_agent_count = 0

    while True:
        agent_loop(state)                         # 内层 ReAct 循环

        if state.running_agent_count == 0:
            break                                  # 无后台 agent，真正结束

        # 等待任一 agent 完成（零轮询，asyncio 原生阻塞）
        notification = await state.notification_queue.get()
        notifications = [notification]
        # drain 队列中所有已到达的通知
        while not state.notification_queue.empty():
            notifications.append(state.notification_queue.get_nowait())

        # 注入通知为 user message
        for n in notifications:
            state.messages.append({"role": "user", "content": n["message"]})

        # 重入 agent_loop 处理新消息
```

**CC 参考**：CC 用全局 commandQueue（模块级单例）+ sleep(100) 轮询。
我们用 `state.notification_queue`（asyncio.Queue，每个 coordinator 实例一个）+ `await queue.get()`。
比 CC 更优雅（原生异步阻塞），且支持多 run 并发（CC 是单用户 CLI 不需要）。

**数据流**：spawn_agent 后台协程完成 → `queue.put(notification)` → coordinator_loop 取出 → 注入 messages → 重入 agent_loop。全程不查 DB。

### D3: 通知格式

参考 CC 的 `<task-notification>` 格式：

```xml
<task-notification>
<agent-run-id>42</agent-run-id>
<role>researcher</role>
<status>completed</status>
<result>findings...</result>
</task-notification>
```

由 `format_task_notification()` 生成（已实现在 spawn_agent.py），注入为 user message。

### D4: CoordinatorResult 统一返回

```python
@dataclass
class CoordinatorResult:
    run_id: str
    mode: str                          # 'pipeline' / 'autonomous'
    output: str                        # 最终输出
    node_outputs: dict[str, str] | None  # 管线模式中间节点输出
    agent_runs: list[dict] | None      # 自主模式 agent 执行记录
```

管线模式：从 PipelineResult 转换，output = final_output，node_outputs = outputs。
自主模式：output = agent 最终回复，agent_runs = list_agent_runs 查询结果。

### D5: Coordinator Agent 工具集

Coordinator 只有一个工具：`spawn_agent`。

**CC 对比**：CC Coordinator 有 Agent + SendMessage + TaskStop 三个工具。
我们 Phase 2 只有 spawn_agent（SendMessage 留到 Phase 5.6，TaskStop 可后续加）。

**为什么无执行工具**：Coordinator 的职责是拆任务和协调，不直接执行。
**为什么无 task_* 工具**：CC Coordinator 也没有 TaskCreate/TaskList/TaskGet。
子 agent 结果通过通知队列自动推送，不需要手动查询。

### D6: agents/coordinator.md 角色 prompt 设计

参考 CC coordinatorMode.ts（~370 行）裁剪，保留核心：
1. 角色定义：你是协调者，拆任务、派 Agent、综合结果
2. 工具说明：spawn_agent 派任务，结果通过 `<task-notification>` 自动回传
3. 任务工作流指引：调研 → 综合 → 实施 → 验证
4. 并行策略：独立任务同时 spawn，有依赖的按序
5. Prompt 编写指南：自包含、先综合再派工、不说"根据你的发现"
6. 汇总策略：所有子 Agent 完成后综合结果

## Risks / Trade-offs

**[agent_loop 重入的消息膨胀]** → 每次重入都带完整历史 messages。对于 Coordinator 场景，消息数通常可控（几轮 spawn + notification）。极端情况下可能需要 compact（Phase 3）。

**[管线名精确匹配]** → Project.pipeline 必须精确匹配 YAML 文件名。简单但不灵活。够用，后续可加模糊匹配或别名。

**[notification_queue 内存生命周期]** → Queue 挂在 AgentState 上，coordinator_loop 结束即回收。不存在泄漏风险。
