## Why

Phase 0–5 已经把引擎跑通 (agent loop, pipelines, hooks, permissions, skills, MCP, claw bus, langgraph interrupt, sandbox), 但目前没有面向 Web 前端 / 外部系统的统一 HTTP 入口 — `src/api/*.py` 全是 0 字节占位符, `src/main.py` 只挂了 `/health`。Phase 6.1 要补齐 REST API 层, 让前端 (将来 Phase 6.4) 和外部 caller 能触发并实时观察 chat / pipeline / 自主三种业务链路。

同时, 当前 Coordinator 用 `coordinator_loop` 这个 thin wrapper 把 `agent_loop` 包起来, 用 in-process `asyncio.Queue` 接 sub-agent 通知 — 这套机制只在"一次 HTTP 请求内全部跑完"的模型下成立。一旦把 chat / 自主放到 HTTP server 上, sub-agent 经常跑得比单次 HTTP turn 更长, 必须有一个 per-session 的长跑 actor 来跨 HTTP turn 持有"还在跑的 worker", 同时让 SSE 客户端可以断开重连而不丢消息。

## What Changes

- **新增 REST API 层** (`src/api/*.py`): 5 个触发端点 + 配套查询, API Key 鉴权, SSE 流式输出
  - `POST /api/projects/{id}/sessions` — 创建 chat session, 指定 mode
  - `POST /api/sessions/{id}/messages` — 发消息 (chat / autonomous 共用, 由 `session.mode` 区分)
  - `GET  /api/sessions/{id}/events` — SSE 订阅, 支持 `Last-Event-ID` 断线续传
  - `POST /api/projects/{id}/pipelines/{name}/runs?stream=` — 触发命名 pipeline (Phase 4 blog/courseware)
  - `POST /api/runs/{id}/resume` — 恢复 LangGraph 暂停的 pipeline run (Phase 5.6)
  - `POST /api/runs/{id}/cancel` — 取消任意 run
  - 列表/查询: `GET /api/projects`, `GET /api/sessions/{id}`, `GET /api/runs/{id}`
- **新增 SessionRunner**: per-session 长跑协程, 跨 HTTP turn 持有 chat AgentState 和 in-flight worker, 监听 PG 消息流, 推送事件给 SSE 订阅者, idle 60s 后自动退出
- **BREAKING — 删除 `src/engine/coordinator.py` 的 `coordinator_loop`**: Coordinator 不再被外部 wrapper 包裹, 直接以 `agents/coordinator.md` 这个 role 跑标准 `agent_loop`。chat 模式同理走 `agents/assistant.md`。两种 mode 共享同一份 SessionRunner 代码
- **BREAKING — `spawn_agent` 通知机制改造**: 后台 worker 完成时不再 `notification_queue.put()`, 改为 INSERT `Conversation.messages` (user-role `<task-notification>`) + 唤醒同进程 SessionRunner (in-process `asyncio.Event`), 跨进程通过 PG `LISTEN/NOTIFY` 兜底
- **chat_sessions 表增列 `mode VARCHAR(20)`**: 取值 `chat | autonomous`, 决定加载哪个 role file (assistant.md vs coordinator.md)
- **API Key 鉴权**: 启动时从 `settings.api_keys` 读, 请求 header `X-API-Key` 校验, 失败返回 401
- **进程 lifespan 整合**: FastAPI startup 启动 SessionRunner GC 任务, shutdown 时优雅关停所有 SessionRunner

非目标 (留给后续 phase):
- Phase 6.2 telemetry 指标埋点 (会暴露 `sessions_active` 等, 但仪表盘 + 报警在 6.2)
- Phase 6.3 主动通知 (Notify)
- Phase 6.4 Web 前端
- 多进程部署的 sticky routing — 起步阶段 `--workers 1`, sticky / advisory lock 是 6.x 的部署方案而不是 6.1 的代码改动

## Capabilities

### New Capabilities
- `rest-api`: FastAPI 路由层, 端点定义, 请求/响应 schema, API Key 鉴权, SSE 流式封装, 错误格式
- `session-runner`: per-session 长跑协程的生命周期 (出生/存活/死亡/复活), idle GC, in-process 注册表, PG 消息流监听, SSE 事件分发

### Modified Capabilities
- `spawn-agent`: 通知机制从 `parent_state.notification_queue.put()` 改为 PG INSERT + SessionRunner 唤醒; 后台 worker callback 不再依赖父协程在线
- `session-manager`: `chat_sessions` 表增加 `mode` 字段 (chat / autonomous), `resolve_session()` 接受并写入 mode
- `pipeline-run`: 删除 "Coordinator autonomous mode" scenario (不再有 run_coordinator 这个调用方)
- `agent-run-lifecycle`: "AgentRun is a pure audit record" 重写, 用 SessionRunner.wakeup 替代 notification_queue 描述

### Removed Capabilities
- `coordinator-loop`: 整个 capability 删除。Coordinator 不再需要外部 wrapper, role file + 标准 `agent_loop` + SessionRunner 已经覆盖原职责
- `coordinator-routing`: 整个 capability 删除。`run_coordinator` 入口函数被 REST 端点替代 — autonomous 走 `POST /api/sessions/{id}/messages`, pipeline 走 `POST /api/projects/{id}/pipelines/{name}/runs`, 不再需要"统一入口 + 内部 if/else 路由"
- `blog-pipeline`: 删除 "accessible via run_coordinator" 单条 requirement (pipeline 实现本身不变, 只是入口换成 REST)
- `courseware-pipeline`: 同上, 删除 "accessible via run_coordinator" 单条 requirement

## Impact

- **代码新增**: ~800 行
  - `src/api/*.py` 填充 (sessions, runs, projects, auth) ~400 行
  - `src/engine/session_runner.py` 新建 ~300 行
  - `src/engine/session_registry.py` 新建 (全局 dict + lock + GC) ~100 行
- **代码删除**: ~150 行
  - `src/engine/coordinator.py` 整个文件
  - `src/tools/builtins/spawn_agent.py` 中通知队列相关分支
  - 相关测试 (`scripts/test_coordinator*.py`)
- **数据库迁移**: `chat_sessions` 加 `mode` 列, 默认 `chat`
- **依赖**: 无新增 (FastAPI / SQLAlchemy / asyncpg 已在用)
- **配置**: `settings.api_keys: list[str]`, `settings.session.idle_timeout_seconds: int = 60`, `settings.session.max_age_seconds: int = 86400`
- **Phase 5.5 Claw Bus 不受影响**: chat gateway 走的是另一条入站路径, 但内部 dispatch 也会迁移到 SessionRunner (本提案范围内)
- **Phase 5.6 LangGraph pipeline interrupt 不变**: `/api/runs/{id}/resume` 只是把现有 `gateway-resume` 的 Claw bus 命令路径暴露成 HTTP 端点, 底层 PostgresSaver checkpointer 不动
- **部署**: 起步要求 `--workers 1`, 多进程部署见 memory `deployment_risks_session_runner.md`
