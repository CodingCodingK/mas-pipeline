## Why

Phase 2.5 写了最小 create_run，但缺 get/list/update 和 Redis 状态同步。Phase 2.7 Pipeline Engine 需要更新 Run 状态、2.8 Coordinator 需要查询 Run 列表、Phase 6 API 层需要 Redis 做实时状态轮询。

## What Changes

- 扩展 `src/engine/run.py` — 补全 get_run / list_runs / update_run_status / finish_run + Redis 同步
- 新增 RunStatus 枚举 + 状态机校验（InvalidTransitionError）
- create_run 扩展签名（session_id, pipeline 参数）
- 每次状态变更同步写 Redis Hash

## Capabilities

### Modified Capabilities
- `pipeline-run`: 从最小 create_run 扩展为完整 CRUD + 状态机 + Redis 同步

## Impact

- 修改文件：`src/engine/run.py`
- 数据库：`workflow_runs` 表已存在
- Redis：新增 `workflow_run:{run_id}` Hash key
- 下游：Pipeline Engine（2.7）消费 update_run_status / finish_run，Coordinator（2.8）消费 list_runs
