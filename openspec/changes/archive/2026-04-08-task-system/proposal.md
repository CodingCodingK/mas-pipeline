## Why

管线引擎执行博客生成时，每个节点（researcher → writer → reviewer → editor）对应一个 task。Task System 记录每个 task 的状态流转（pending → in_progress → completed/failed），支持 DAG 依赖（writer 等 researcher 完成才开始）。Coordinator 查 task 状态汇报进度，Phase 6 Telemetry 统计每个 task 耗时。

## What Changes

- 在 `src/models.py` 增加 Task ORM model
- 新增 `src/task/manager.py` — create_task / list_tasks / get_task / claim_task / complete_task / fail_task / check_blocked
- claim_task 用 SELECT FOR UPDATE 行锁，防止多 worker 重复认领
- check_blocked 查 blocked_by 数组中的 task 是否全部 completed

## Capabilities

### New Capabilities
- `task-lifecycle`: Task 的创建、认领（行锁）、完成/失败、DAG 依赖检查

### Modified Capabilities
（无）

## Impact

- 新增文件：`src/task/manager.py`
- 修改文件：`src/models.py`（增加 Task model）
- 数据库：`tasks` 表已在 Phase 0 建好
- 下游：Pipeline Engine 创建和管理 task，Coordinator 查询 task 状态
