## Context

`projects` 表已存在（Phase 0 init_db.sql），字段：id, user_id, name, description, pipeline, config, status, created_at, updated_at。`src/auth/user.py` 提供 `get_current_user()` 获取 user_id。`src/db.py` 提供 `get_db()` async session。

## Goals / Non-Goals

**Goals:**
- 提供 Project dataclass 和 5 个 CRUD async 函数
- 创建项目时自动建 uploads 目录
- archive 为软删除（status 改 archived）
- 所有查询按 user_id 过滤

**Non-Goals:**
- 不做分页（Phase 6 API 层加）
- 不做权限检查（单用户模式，Phase 5 加）
- 不做 project config 校验（Phase 2.7 管线引擎消费时再校验）

## Decisions

### D1. 引入 SQLAlchemy ORM model 层

Phase 2 起有 projects / pipeline_runs / tasks / documents 等多张表做 CRUD，raw SQL 重复劳动多。引入 ORM：

- 新建 `src/models.py` 统一定义所有 ORM model（DeclarativeBase）
- CRUD 用 ORM（session.add / session.get / 属性赋值）
- 复杂查询仍可 raw SQL
- 业务层直接用 ORM model 实例做数据模型，不再单独定义 dataclass
- 改造 user.py 使用 ORM model，去掉 User dataclass

`src/db.py` 已有 AsyncEngine + AsyncSession + get_db()，零新增依赖。

### D2. uploads 目录在项目根下

`{PROJECT_ROOT}/uploads/{project_id}/`。Phase 2.3 File Manager 上传文件到此目录。创建项目时 `os.makedirs(path, exist_ok=True)`。

### D3. archive 是软删除

`archive_project()` 只把 status 改成 `'archived'`，`list_projects()` 默认只返回 `status='active'`。不删数据、不删文件。物理清理是运维操作，不在代码里做。

### D4. updated_at 手动更新

PostgreSQL 不自动更新 `updated_at`。在 update/archive 操作中显式 SET updated_at = NOW()。

## Risks / Trade-offs

- **[uploads 目录清理]** → archive 不删文件，靠运维脚本清理。Phase 2 范围内可接受。
- **[无分页]** → list_projects 返回全部 active 项目。单用户几十个项目没问题，Phase 6 加 limit/offset。
