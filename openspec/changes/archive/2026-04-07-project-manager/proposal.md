## Why

Pipeline Run、File Manager、Task System 都以 project_id 为核心外键。没有 Project Manager 就无法创建项目、关联资源或启动管线。这是 Phase 2 的数据归属中枢。

## What Changes

- 新增 `src/project/manager.py` — Project dataclass + CRUD 函数
- 创建项目时自动建 `uploads/{project_id}/` 目录
- archive 为软删除（status → archived），不物理删除数据
- 所有操作按 user_id 隔离

## Capabilities

### New Capabilities
- `project-crud`: 项目的创建、查询、列表、更新、归档操作

### Modified Capabilities
（无）

## Impact

- 新增文件：`src/project/manager.py`
- 依赖：`src/auth/user.py`（get_current_user 提供 user_id）
- 数据库：`projects` 表已在 Phase 0 建好
- 文件系统：创建 `uploads/{project_id}/` 目录
- 下游：Pipeline Run、File Manager、Coordinator 将消费 Project CRUD
