## 1. RunStatus 枚举 + 状态机

- [ ] 1.1 在 `src/engine/run.py` 新增 RunStatus 枚举、VALID_TRANSITIONS、InvalidTransitionError

## 2. 扩展 CRUD

- [ ] 2.1 扩展 create_run（session_id, pipeline 参数 + Redis 同步）
- [ ] 2.2 实现 get_run(run_id) / list_runs(project_id)
- [ ] 2.3 实现 update_run_status(run_id, status) — 状态机校验 + PG + Redis
- [ ] 2.4 实现 finish_run(run_id, status) — 终态 + finished_at + Redis

## 3. 验证

- [ ] 3.1 创建 `scripts/test_workflow_run.py` — 状态机校验、CRUD、Redis 同步
