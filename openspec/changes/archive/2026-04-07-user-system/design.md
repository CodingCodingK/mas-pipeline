## Context

Phase 0 已建好 `users` 表（id, name, email, config, created_at）和 seed 数据（default 用户）。`config/settings.yaml` 已有 `default_user` 配置段。Phase 2 所有模块需要 user_id 做数据归属。

当前无用户模块代码，需要新建 `src/auth/user.py` 提供用户获取能力。

## Goals / Non-Goals

**Goals:**
- 提供 `User` 数据模型和 `get_current_user()` 函数
- 单用户模式：从配置读默认用户名，查数据库返回完整 User
- 下游模块（Project/File/Task）能通过一行调用拿到 user_id

**Non-Goals:**
- 不实现认证（JWT / OAuth）— Phase 6
- 不实现多用户切换
- 不实现用户注册/修改 API
- 不做密码/token 管理

## Decisions

### D1. User 模型用 dataclass 而非 Pydantic

项目当前所有模型（ToolResult, AgentState, LLMResponse 等）都用 dataclass。保持一致。Phase 6 加 API 层时可以单独给 endpoint 写 Pydantic schema，不影响内部模型。

### D2. get_current_user() 查数据库而非纯配置

从 `settings.yaml` 读 `default_user.name`，然后查 `users` 表拿完整记录（含 id）。原因：下游需要 `user_id`（整数 FK），纯配置无法提供。查一次缓存即可。

### D3. 模块级缓存避免重复查询

`get_current_user()` 首次调用查 DB，结果缓存在模块变量。整个进程生命周期内默认用户不变，无需每次查。

## Risks / Trade-offs

- **[DB 未初始化]** → `get_current_user()` 找不到用户时抛明确异常，提示运行 init_db.sql
- **[缓存不失效]** → 单用户模式不需要失效。Phase 6 多用户时此函数会被替换为从请求上下文获取
