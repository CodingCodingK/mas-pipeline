## Context

Phase 2.5 已有最小 `create_run(project_id)` 和 `WorkflowRun` ORM model。`workflow_runs` 表字段：id, project_id, session_id, run_id(unique), pipeline, status, started_at, finished_at, metadata。Redis 已有连接层（`src/db.py` 的 `get_redis()`）。

## Goals / Non-Goals

**Goals:**
- 完整 CRUD：create（扩展签名）/ get / list / update_status / finish
- RunStatus 枚举 + 状态机校验（pending → running → completed/failed）
- Redis Hash 同步：每次状态变更写 `workflow_run:{run_id}`
- InvalidTransitionError 异常

**Non-Goals:**
- 不做节点级 Redis 状态（current_node / nodes 是 2.7 Engine 的事）
- 不做 Run 删除（无业务需求）
- 不做 Run 分页查询（Phase 6 API 层加）

## Decisions

### D1. RunStatus 枚举 + 状态机

RunStatus(str, Enum): PENDING / RUNNING / COMPLETED / FAILED。
合法转换：pending → running, running → completed, running → failed。
completed 和 failed 是终态，不可再转。
违反转换规则抛 InvalidTransitionError。

### D2. Redis Hash 同步

每次状态变更调 `_sync_to_redis(run)`，用 HSET 写入 `workflow_run:{run_id}` Hash。
字段：project_id, pipeline, status, started_at, finished_at。
2.7 Engine 后续加 current_node / nodes 字段，Hash 结构天然支持增量加字段。
finish_run 时额外写 finished_at。
不设 TTL（Run 记录长期保留）。

### D3. create_run 扩展

签名扩展为 `create_run(project_id, session_id=None, pipeline=None)`。
2.5 的调用点不传 session_id/pipeline，默认 None，向后兼容。

### D4. finish_run 便捷函数

`finish_run(run_id, status)` = update_status + 设 finished_at。
只接受 COMPLETED 和 FAILED 两个终态 status。

## Risks / Trade-offs

- **[Redis 可用性]** → Redis 挂了不影响核心流程（PG 是 source of truth），但 _sync_to_redis 会报错。Phase 2 不做降级处理（try/except log warning），Phase 5 可加。
