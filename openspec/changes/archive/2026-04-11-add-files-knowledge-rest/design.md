## Context

Phase 6.4 Web 前端开工前必须补齐 files / knowledge 两块的 REST 接口。本 change 的核心难点不是 CRUD（那是机械工作），而是 **ingest 的实时进度推送** —— 用户希望看到 100 页 PDF 在「parsing → chunking → embedding 47/142 → done」的实时变化。

设计上有两个关键决策需要展开说明：(1) 为什么走 D1 内存 job 表而不是 EventBus；(2) 进度回调如何插入现有 ingest 流程而不污染业务代码。

**Export 不在本 change 范围**：开工时撞到现实差距 —— `WorkflowRun` 没有 `final_output` 字段，`PipelineResult` 只活在内存。Export 拆到 Change 1.5（产出持久化）+ 1.6（exporter + REST）两步完成。

## Decision 1: D1 内存 job 表 vs D2 走 EventBus

### 候选方案

**D1 - 独立内存 job 表 + asyncio.Queue**
- `JobRegistry` 单例存 `dict[str, Job]`
- `Job.queue: asyncio.Queue` 是 1:1 通道（只有 SSE 那一个消费者）
- ingest 通过 `progress_callback` 把事件 put 进 queue
- SSE endpoint 从 queue get，直到 done/failed

**D2 - 走 Phase 6.3 EventBus**
- ingest 内部 `bus.emit("ingest_progress", {job_id, ...})`
- SSE endpoint 订阅 bus 的 `ingest_progress` 频道，按 job_id 过滤
- 复用 telemetry / notify 同构的 fan-out 模式

### 为什么选 D1

1. **场景本质是 1:1**: 实时进度只有「触发 ingest 的那个用户」会看，没有其他订阅者。EventBus 的 fan-out 在这里是负载（每条进度都广播给 telemetry 和 notify 订阅者后被它们丢弃）。
2. **CC 同场景的选择**: CC 的 `BashTool` 后台命令实时输出走的是局部 channel + monitor 模式，**不**经过 CC 内部的事件总线。CC 把「实时局部进度」和「全局事件」做成两套独立系统是有原因的 —— 进度的高频和瞬时性会污染事件总线的语义。
3. **测试简单**: D1 不需要 mock bus，单测直接 instantiate `JobRegistry` 即可。
4. **未来不冲突**: 若将来 notify 层真要订阅「ingest 完成」事件，只需在 ingest 末尾 `bus.emit("ingest_completed", ...)` 一行 —— 「实时进度走 D1」和「完成事件走 bus」可以共存。
5. **Linus 准则**: 不解决想象中的问题。当前没有任何「另一个模块需要看 ingest 进度」的需求。

### D1 的代价

- 进程重启后 job 表丢，前端只能重新触发 ingest。**可接受** —— 单进程部署、PG 里 Document.parsed 字段可推断「上次 ingest 是否成功」。
- 没有跨进程协调。**可接受** —— 当前是单进程部署（`.plan/rest_api_deployment_risks.md` 已记载）。
- 内存可能膨胀。**已缓解** —— `JobRegistry.cleanup_finished(max_age_sec=86400)` 后台任务每小时清理。

## Decision 2: progress_callback 注入 vs ingest 直接持有 bus 引用

### 选择: 注入 callback

`ingest_document(project_id, doc_id, *, progress_callback=None)` 接受可选 callback。embedder 同构。

### 为什么不让 ingest 直接持有 JobRegistry 引用

1. **业务代码无感**: ingest 仍可被脚本、测试、未来的 CLI 工具直接调用，**不依赖** Web/REST 基础设施。
2. **测试可用 spy**: 单测直接传一个收集事件的 list.append，不需要 mock JobRegistry。
3. **与 D1/D2 决策正交**: 哪怕将来切到 D2，callback 签名 `Callable[[dict], Awaitable[None]]` 不变 —— 只是 callback 内部从「put queue」改成「bus.emit」。
4. **零依赖扩散**: `src/rag/` 不需要 import `src/jobs/`。

### Callback 调用契约

```python
ProgressCallback = Callable[[dict], Awaitable[None]]

# 调用点和语义:
await cb({"event": "parsing_started"})
await cb({"event": "parsing_done", "text_length": 12345})
await cb({"event": "chunking_done", "total_chunks": 142})
await cb({"event": "embedding_progress", "done": 100, "total": 142})
await cb({"event": "embedding_progress", "done": 142, "total": 142})
await cb({"event": "storing"})
await cb({"event": "done", "chunks": 142})
# 或异常路径:
await cb({"event": "failed", "error": "embedding API timeout"})
```

`ingest_document` 在 try/except 里捕获所有异常，发 `failed` 事件后再 raise。

## Decision 3: SSE 端点 vs WebSocket vs 长轮询

选 SSE，理由同 Phase 6.3 (`add-notify-layer`):

- 单向流，不需要 WebSocket 的双向能力
- HTTP/1.1 原生兼容，浏览器 `EventSource` 现成支持
- 鉴权走现有 `X-API-Key` header，无 WS 升级握手的鉴权额外路径
- 已经有 `/api/notify/stream` 和 `/api/sessions/{id}/events` 两个 SSE 实现做范本

## Decision 4: chunks 接口分页 vs 全量

选分页 `?offset=0&limit=20`，最大 limit=100。

理由：100 页 PDF 可能产 500+ chunk，全量返回响应体 MB 级。对齐 CC `Read` 工具的 offset/limit 模式。前端实现「点击文件 → 看前 20 个 chunk → 滚动加载下一页」很自然。

## Decision 5: src/jobs/ 单独开目录 vs 塞进 src/api/jobs.py

选单独开 `src/jobs/`。

理由：

- `Job` / `JobRegistry` 是业务对象，不是 HTTP 路由 —— 与 `src/api/jobs.py` (REST 包装) 职责不同
- 将来可能有其它长任务也用这套（导出大 PDF、批量 embed、数据迁移工具）
- 测试隔离更干净 —— `test_jobs_registry.py` 不需要 import FastAPI

布局：
```
src/jobs/
  __init__.py    # 导出 Job, JobRegistry
  job.py         # Job dataclass + 生命周期方法
  registry.py    # JobRegistry 单例 + cleanup 后台任务
src/api/
  jobs.py        # REST 路由：GET /jobs/:id, GET /jobs/:id/stream
```

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 进程重启 job 丢 | 单进程部署可接受；PG `Document.parsed` 是真相之源 |
| `asyncio.create_task` 漏 await 异常 | Job 自身 try/except 捕获并写 `failed` 事件；任务对象 `add_done_callback` 记日志 |
| Queue 满阻塞 ingest | Queue 大小 1000，drop-oldest 策略；进度事件本来就可丢 |
| 用户多 tab 同时打开 SSE | Job.queue 只有一个消费者；后开的 tab 拿不到流。可接受 —— 同时开两个 tab 看同一个 ingest 是边缘场景 |
| ingest 业务代码侵入 | callback 是可选参数，传 None 即原行为；调用方零修改 |

## Migration Notes

无 schema 变更。无现有调用方修改。

## Open Questions

无。所有决策已和用户对齐于 `.plan/web_frontend_plan.md`。
