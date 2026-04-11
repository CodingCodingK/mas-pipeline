## Why

Phase 6.4 (Web 前端) 即将开工，但 `src/api/` 下有 4 个 0 字节 stub 文件 (`files.py`, `knowledge.py`, `telemetry.py`, `export.py`)。核查后发现：

- **telemetry** 实际挂在 `src/telemetry/api.py`，已就绪 ✅
- **notify** 在 `src/notify/api.py`，已就绪 ✅
- **files / knowledge 两块没有任何 REST 暴露**：
  - `src/files/manager.py` 业务层已存在
  - `src/rag/` 完整 RAG 模块已存在（ingest/retriever/embedder/chunker/parser）

前端依赖这些端点：上传文件、列文件、删文件、触发 ingest、看 chunks。在前端开工前必须补齐，否则项目详情页 / 知识库 tab 会全 404。

**关键体验决策**：ingest 是慢操作（一个 100 页 PDF 走 parse → chunk → embed 可能 1–5 分钟），用户希望前端能**实时看到进度**。本 change 引入轻量 job 追踪 + SSE 进度流（D1 方案 —— 独立内存 job 表 + asyncio.Queue，对齐 CC `BashTool` 后台命令的设计）。

**Export 不在本 change 范围**：开工时撞到 spec/现实不一致 —— `WorkflowRun` 没有 `final_output` 字段，pipeline 结果只活在内存的 `PipelineResult` dataclass 里，跑完即失。Export 需要先做 Change 1.5 (`add-pipeline-result-persistence`) 把产出落盘，再做 Change 1.6 (`add-export-rest`) 包业务层 + REST。本 change 只负责 files / knowledge / jobs 三块。

## What Changes

- **删除** 4 个 0 字节 stub: `src/api/{files,knowledge,telemetry,export}.py`
- **新建** `src/api/files.py` —— 文件 CRUD REST
  - `POST   /api/projects/{project_id}/files` （multipart upload）
  - `GET    /api/projects/{project_id}/files`
  - `DELETE /api/projects/{project_id}/files/{file_id}`
- **新建** `src/api/knowledge.py` —— 知识库 REST
  - `POST /api/projects/{project_id}/files/{file_id}/ingest` → 立即 202 + `{job_id}`
  - `GET  /api/projects/{project_id}/files/{file_id}/chunks?offset=0&limit=20`（默认 20，最大 100）
  - `GET  /api/projects/{project_id}/knowledge/status` （文件总数 / 已索引数 / 总 chunk 数）
- **新建** `src/jobs/` —— 内存 job 追踪基础设施（D1）
  - `src/jobs/registry.py` —— `JobRegistry` 单例：`create(kind) -> Job`、`get(job_id)`、`list()`、`cleanup_finished(max_age_sec)`
  - `src/jobs/job.py` —— `Job` 数据类：`id, kind, status (pending/running/done/failed), error, started_at, finished_at, queue: asyncio.Queue, last_event` + `emit(event_dict)` 写队列同时存最后事件
  - 内存存储，进程重启即丢；自动清理 24h 前已完成 job
- **新建** `src/api/jobs.py` —— job 查询 + SSE 进度流
  - `GET /api/jobs/{job_id}` —— 单点查询元信息
  - `GET /api/jobs/{job_id}/stream` —— SSE 持续 yield 进度事件直到 `done`/`failed`
- **改动** `src/rag/ingest.py` —— `ingest_document(...)` 增加可选 `progress_callback: Callable[[dict], Awaitable[None]] | None`
  - 在每个阶段调用 callback 发事件：`parsing_started` / `parsing_done` / `chunking_done` / `embedding_progress` / `storing` / `done` / `failed`
- **改动** `src/rag/embedder.py` —— `embed(...)` 增加可选 `progress_callback`，每完成一批（100 条）触发一次 tick
- **改动** `src/main.py` lifespan —— 注册 3 个新 router (files / knowledge / jobs)，启动 `JobRegistry` 后台清理任务

## Capabilities

### New Capabilities

- `file-rest-api`: HTTP 接口暴露文件管理 —— 上传、列表、删除
- `knowledge-rest-api`: HTTP 接口暴露知识库 —— 触发 ingest、分页 chunk 预览、索引状态查询
- `job-tracking`: 内存 job 注册表 + 进度事件队列 + SSE 流，用于追踪长任务（首个使用者：ingest）

### Modified Capabilities

- `embedding` —— `embed()` 增加可选 progress callback 参数（向后兼容，调用方不传则等同原行为）

## Impact

- **新文件**: `src/api/files.py`, `src/api/knowledge.py`, `src/api/jobs.py`, `src/jobs/__init__.py`, `src/jobs/job.py`, `src/jobs/registry.py`, `scripts/test_rest_files.py`, `scripts/test_rest_knowledge.py`, `scripts/test_rest_jobs.py`, `scripts/test_jobs_registry.py`, `scripts/test_ingest_progress.py`
- **修改**: `src/rag/ingest.py` (加 callback 参数), `src/rag/embedder.py` (加 callback 参数), `src/main.py` (lifespan + router 挂载)
- **删除**: `src/api/files.py` (0 字节 stub), `src/api/knowledge.py` (0 字节 stub), `src/api/telemetry.py` (0 字节 stub), `src/api/export.py` (0 字节 stub) —— 然后 files/knowledge 重建为真实文件，telemetry/export 永久删除
- **DB schema**: 无变化 —— job 表存在内存
- **依赖**: 无新包 —— `python-multipart` 用于文件上传，FastAPI 默认依赖；`httpx` 已有
- **回归风险**: 低 —— 新接口都是纯添加；唯二被改的现有文件是 `src/rag/ingest.py` 和 `src/rag/embedder.py`，且只新增可选参数，调用方零修改即向后兼容
- **不在范围内**:
  - Export REST + 业务（拆到 Change 1.6，依赖 1.5 的产出持久化）
  - 检索接口（Agent 通过工具直接调用 retriever，不需 REST）
  - 持久化 job 表（重启即丢，可接受；前端在重启后只是看不到进度，重新触发即可）
  - Agent / Pipeline 的 REST 接口（这是 Change 2 `add-agent-pipeline-layered-storage`）
