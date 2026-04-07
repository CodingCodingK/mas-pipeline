## Why

Phase 2 的所有模块（Project Manager、File Manager、Task System、Pipeline Run）都需要 user_id 来做数据归属。当前系统没有用户概念，无法创建 Project 或关联资源。需要一个最简单的用户系统作为 Phase 2 的基础依赖。

Phase 1 单用户足够——先跑通管线，Phase 6 再加多用户认证（JWT）。

## What Changes

- 新增 `src/auth/user.py` — User 模型 + `get_current_user()` 函数
- 单用户模式：从 `settings.yaml` 读 `default_user` 配置，返回固定用户
- 数据库 `users` 表插入默认用户记录（利用 Phase 0 已建好的表）
- 预留多用户接口签名，但不实现认证逻辑

## Capabilities

### New Capabilities
- `user-identity`: 用户身份获取——单用户模式下从配置读取默认用户，返回 User 模型

### Modified Capabilities

（无）

## Impact

- 新增文件：`src/auth/user.py`
- 配置变更：`config/settings.yaml` 增加 `default_user` 段
- 数据库：`users` 表需要 seed 默认用户（`scripts/init_db.sql` 已建表，需补 INSERT）
- 下游依赖：Project Manager、File Manager、Task System 将消费 `get_current_user()`
