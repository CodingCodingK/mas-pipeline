## Context

`tasks` 表已存在，字段：id, run_id(FK→pipeline_runs), subject, description, status, owner, blocked_by(INTEGER[]), result, metadata, created_at, updated_at。管线引擎（2.7）为每个节点创建 task，按拓扑顺序 claim 和执行。

## Goals / Non-Goals

**Goals:**
- Task ORM model + 7 个管理函数
- claim_task 用 SELECT FOR UPDATE 行锁防并发认领
- check_blocked 检查 DAG 依赖是否满足
- 状态流转：pending → in_progress → completed / failed

**Non-Goals:**
- 不做 cancelled 状态（Phase 5 abort 机制加）
- 不做任务优先级/调度（管线引擎决定执行顺序）
- 不做超时自动 fail（Phase 5 加）

## Decisions

### D1. claim_task 用 SELECT FOR UPDATE

单事务内锁行 → 检查 status → 改 in_progress + 写 owner。Phase 2 单进程无竞争，但零成本预留给多 worker 场景。

### D2. check_blocked 查 blocked_by 数组

`blocked_by` 存的是 task id 数组。check_blocked 查这些 id 对应的 task 是否全部 status='completed'。全 completed 返回 False（不阻塞），否则返回 True（阻塞中）。

### D3. complete_task / fail_task 分开

complete_task 写 result（产出文本）+ status='completed'。fail_task 写 result（错误信息）+ status='failed'。不合并成一个函数，语义清晰。

### D4. Task model 放 models.py

和 User / Project / Document 一致。

## Risks / Trade-offs

- **[run_id FK]** → tasks.run_id 引用 pipeline_runs 表，Pipeline Run（2.6）还没实现。Task model 先定义字段，测试时手动插 pipeline_runs 记录
- **[blocked_by 不做级联更新]** → task 被删除不会自动从其他 task 的 blocked_by 里移除。Phase 2 不删 task，可接受
