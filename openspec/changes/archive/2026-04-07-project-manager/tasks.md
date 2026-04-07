## 1. ORM Model 层

- [x] 1.1 创建 `src/models.py` — DeclarativeBase + User / Project ORM model（匹配 init_db.sql 表结构）
- [x] 1.2 改造 `src/auth/user.py` — 去掉 User dataclass，改用 ORM model，get_current_user 用 session.execute(select(User))

## 2. Project Manager

- [x] 2.1 实现 `src/project/manager.py` — create_project / get_project / list_projects / update_project / archive_project（全部用 ORM）

## 3. 验证

- [x] 3.1 创建 `scripts/test_project_manager.py` — 验证全部 CRUD + uploads 目录 + archive 软删除 + list 排除 archived
