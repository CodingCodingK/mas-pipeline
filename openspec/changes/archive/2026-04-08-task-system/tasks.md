## 1. ORM Model

- [x] 1.1 在 `src/models.py` 中增加 Task model（匹配 tasks 表结构，含 ARRAY(Integer) 类型的 blocked_by）

## 2. Task Manager

- [x] 2.1 实现 `src/task/manager.py` — create_task / list_tasks / get_task / claim_task(FOR UPDATE) / complete_task / fail_task / check_blocked

## 3. 验证

- [x] 3.1 创建 `scripts/test_task_system.py` — 验证创建、认领（含重复认领报错）、完成、失败、DAG 依赖检查
