## Context

Phase 0–5 已经把引擎跑通, 但 `src/api/*.py` 全是占位符, `src/main.py` 只挂了 `/health`。Phase 6.1 要补齐 HTTP 入口。同时 chat / autonomous 模式必须解决"sub-agent 跨 HTTP turn 跑"的问题: 当前 `coordinator_loop` 用 in-process `asyncio.Queue` 接 sub-agent 通知, 这只在 CLI 风格的"一次调用全部跑完"模型下成立, 一旦放到 HTTP server 上 — 用户发完消息就断开, 几分钟后回来 — 通知队列已经随着 handler 函数销毁了。

讨论阶段 (见 memory `architecture_routing_cc_vs_ab.md`) 对比了 CC / 走法 A / 走法 B 三种架构, 决定走 **走法 A**: per-session 长跑 SessionRunner 协程 + PG 作为持久消息流。理由记录在 memory `decision_phase61_routing.md`, 部署风险记录在 `deployment_risks_session_runner.md`。

## Goals / Non-Goals

**Goals:**
- 提供 5 个触发端点 + 配套查询, 覆盖 chat / pipeline / 自主三种业务链路
- chat 和 autonomous **共享同一份代码路径**, 仅通过 `session.mode` 决定加载哪个 role file (对齐 CC `coordinatorMode` 设计)
- 删除 `coordinator_loop` 这个 thin wrapper, Coordinator 退化成普通 role
- per-session SessionRunner 跨 HTTP turn 持有 in-flight worker, 用户断线/重连不丢消息
- SSE 流式推送, 支持 `Last-Event-ID` 断线续传 (backfill 从 `Conversation.messages` 取)
- 单进程部署即可用 (`--workers 1`), 不强依赖跨进程协调

**Non-Goals:**
- Phase 6.2 telemetry 指标埋点 / Prometheus 暴露 — 本提案只在 SessionRunner 内留 hook 点, 仪表盘和报警在 6.2
- Phase 6.3 主动通知 (Notify)
- Phase 6.4 Web 前端
- 多进程部署的 sticky routing / PG advisory lock — 起步阶段强制 `--workers 1`, sticky 是部署侧方案, 不在 6.1 的代码里
- 独立 worker 进程 (Celery/Arq) — 跨小时长 worker 是未来的事
- session 的认证/授权细化 (api key 多租户 / 用户级权限) — 6.1 只做单一 api_keys 列表

## Decisions

### D1: 走法 A (per-session 长跑协程 + PG 消息流), 不走 B

**选择**: SessionRunner 是一个 per-session 的 asyncio.Task, 跨 HTTP turn 存活。HTTP handler 短期, 写完 PG 立即 return。SSE handler 是另一个短期协程, 从 SessionRunner 的事件队列订阅。

**Why not 走法 B (handler-scoped)**: B 把所有循环放在一次 HTTP request 里, 实现简单但 sub-agent 必须在 handler 内全跑完。一旦有跑分钟级的 worker (Phase 6+ 跑测试套件 / 深度规划), 客户端会被长挂的 HTTP 拖死, 中间断线就丢消息。走法 A 的额外代码 (~600 行) 一次性付清, 之后不返工。

**Why not CC 原版**: CC 是单进程 CLI, 不需要 HTTP 适配层。我们 95% 对齐 CC 的 mode 设计, 5% 差异只在 HTTP 入口。

### D2: SessionRunner 的"消息流"用 `Conversation.messages` JSONB list, 不另建 messages 表

**选择**: 复用现有 `conversations.messages` JSONB 字段。"用户输入"和"sub-agent 完成通知"是同一种数据 — 都是 user-role message, 一个走自然语言, 一个走 `<task-notification>` XML 包装 (同 CC)。

**Why**: 引入新 messages 表是过早的关系化。JSONB list 已经够用, append 是单条 UPDATE。未来如果跨 session 查询变多, 再拆表不晚。

**Trade-off**: JSONB 不能加索引到单条消息的字段, 长 conversation 重复反序列化代价高。缓解: in-memory `state.messages` 在 SessionRunner 内是 source of truth, PG 只是落盘 + 复活时 reload。

### D3: 跨进程唤醒兜底用 PG `LISTEN/NOTIFY`, 但 6.1 不强依赖

**选择**: SessionRunner 主路径用 in-process `asyncio.Event`(同进程的 spawn_agent 完成 → set event)。同时挂一个 PG `LISTEN session_wakeup` 协程, 收到 NOTIFY 也能唤醒 — 这是为将来多进程部署预留的口子, 6.1 不强测试。

**Why**: 起步阶段 `--workers 1`, in-process 唤醒是 fast path 也是唯一 path。PG NOTIFY 是 ~20 行预留, 不增加复杂度。

**Alternative considered**: PG 短轮询 (每 N 秒 SELECT) — 否决, 浪费连接 + 延迟差。

### D4: Coordinator / chat assistant 都是普通 role, 删除 `coordinator_loop`

**选择**: `agents/coordinator.md` 已经是 `tools: [spawn_agent]` 的 role, `agents/assistant.md` 是 chat 的 role。SessionRunner 的循环就是标准 `agent_loop`, 不再需要 outer wrapper — sub-agent 通知作为 user-role message 写进 `state.messages`, 下个 turn LLM 自然看到, agent_loop 自己继续跑。

**Why**: outer wrapper (`coordinator_loop`) 是当前架构的特殊情况 — "agent_loop 退出但还有 worker 没回 → 等通知 → 注入消息 → 重进 agent_loop"。SessionRunner 把这层职责天然吸收 (它本来就要 await 消息源), 这层 wrapper 就消失了。Linus 风格: 消除特殊情况。

**BREAKING**: 删除 `src/engine/coordinator.py`, 删除 capability `coordinator-loop`。`AgentState.notification_queue` 字段也删掉。

### D5: chat / autonomous 共用 `POST /api/sessions/{id}/messages`, 用 `session.mode` 区分

**选择**: 单一 messages 端点。`chat_sessions.mode` 字段决定 SessionRunner 启动时加载哪个 role: `mode=chat` → assistant.md, `mode=autonomous` → coordinator.md。后续 turn 不重新加载 role, 由 SessionRunner 持有的 AgentState 决定。

**Why**: 端点表面分裂只会复制路由代码而不能复用业务逻辑。CC 的 `getCoordinatorSystemPrompt()` 也是同一份 QueryEngine, 仅换 system prompt + tool whitelist。

### D6: SSE 流式 + `Last-Event-ID` backfill

**选择**: SSE 端点 `GET /api/sessions/{id}/events`。每个事件带递增的 event_id (= 消息在 conversation 里的索引)。客户端断线重连时, 带上 `Last-Event-ID` header, server 从 `Conversation.messages[last_id+1:]` 推一遍 backfill, 然后切到 SessionRunner 的实时事件流。

**Why not 单独 events 表**: 复用 messages 已经够用 — 事件就是消息流的可视化, 没有"事件比消息粒度更细"的需求。如果未来想推 partial token (流式打字机), 那种 ephemeral event 不落 PG, 直接走内存广播, 不影响 backfill 设计。

### D7: API Key 鉴权, 单一 list

**选择**: `settings.api_keys: list[str]`, 请求 header `X-API-Key` 校验, 失败 401。每个 endpoint 用 FastAPI Depends 注入鉴权函数。

**Why**: 6.1 只服务前端 (Phase 6.4) 和内部脚本, 单 list 够用。多租户 / 用户级权限 留给以后。

### D8: 起步强制 `--workers 1`

**选择**: 文档明确单进程部署。代码层面在 startup 检查 `os.environ.get("WEB_CONCURRENCY", "1")`, 不等于 1 则 print warning。

**Why**: 多进程下同一 session 可能落到不同 worker, 各自创建 SessionRunner, 状态不一致。sticky routing / advisory lock 是部署侧方案, 不在 6.1 范围。Warning 而不是 hard fail, 是因为开发期可能想试多 worker。

## Risks / Trade-offs

完整列表见 memory `deployment_risks_session_runner.md`。提案范围内 (代码侧) 必须处理的:

- **[协程泄漏]** SessionRunner 异常崩溃或 idle 检测 bug → 协程不退出, `_session_runners` dict 无限增长
  → Mitigation: `try/finally` 中无条件 `del`; 独立 GC 任务每分钟扫描, idle > timeout 或 age > 24h 强制清理; startup 时清空 dict

- **[Worker Task 异常静默]** spawn_agent 派出的 sub-agent Task 抛异常没人 catch → SessionRunner 永远等不到 notification, `running_agent_count` 永远 > 0
  → Mitigation: spawn_agent 的 callback 必须 `try/except Exception`, 任何路径都要写一条 failed notification 到 PG; 给 sub-agent 加硬超时 (默认 5 分钟, 可配)

- **[长事务持锁]** SessionRunner 在 `await` 期间持有 PG 事务 → 阻塞其他协程
  → Mitigation: 所有 PG 操作走 `async with get_db()` 短事务, await 任何外部资源前先 commit; code review 重点检查

- **[PG 连接池耗尽]** 1000 活跃 session × 持有连接 → 远超默认 pool_size
  → Mitigation: 配置 `pool_size=20, max_overflow=40`; 严禁在 await 期间持有连接; 监控 hook 点留给 6.2

- **[SSE 慢客户端反压]** 一个浏览器网络慢, SSE buffer 写满 → 拖死整个 SessionRunner
  → Mitigation: SSE push 加超时 (`asyncio.wait_for(send, timeout=5)`); 超时主动断连客户端; SessionRunner 的事件队列设上限 (默认 100), 满了丢老的或断连

- **[in-memory message list 膨胀]** 长 session 累积几千条 → 单 session 10+ MB
  → Mitigation: 复用 Phase 3 compact; in-memory `state.messages` 硬性 cap (默认 200), 超过的从 PG lazy load; SessionRunner 退出时立即释放

- **[进程重启 in-flight worker 丢失]** 服务重启 → asyncio.Task 全死 → 跑了一半的 sub-agent 结果丢
  → Mitigation: 6.1 范围只做"优雅关停 + 标记 in-flight 为 failed", 不做跨重启持久化。文档说明这是已知限制, Phase 6+ 用独立 worker 进程才能彻底解决

- **[BREAKING: coordinator_loop 删除]** 现有 `scripts/test_coordinator*.py` 测试和外部任何直接 import `src.engine.coordinator` 的代码会断
  → Mitigation: 提案内一并删除/重写相关测试; grep 全仓确认无外部依赖
