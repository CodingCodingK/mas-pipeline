## 1. Cleanup

- [x] 1.1 Delete 4 zero-byte stub files: `src/api/files.py`, `src/api/knowledge.py`, `src/api/telemetry.py`, `src/api/export.py` (the latter two are dead code; telemetry actually lives at `src/telemetry/api.py` and is already mounted)

## 2. Job tracking infrastructure (D1)

- [x] 2.1 Create `src/jobs/__init__.py` exporting `Job`, `JobRegistry`, `JobStatus`
- [x] 2.2 Create `src/jobs/job.py`:
  - `JobStatus = Literal["pending", "running", "done", "failed"]`
  - `Job` dataclass: `id: str` (uuid4 hex), `kind: str`, `status: JobStatus`, `error: str | None`, `started_at: datetime`, `finished_at: datetime | None`, `last_event: dict | None`, `queue: asyncio.Queue` (maxsize=1000)
  - `Job.emit(event: dict) -> None` — `queue.put_nowait` with drop-oldest on full, also stores `last_event = event`; if event has `event in {"done", "failed"}`, sets `status` and `finished_at` accordingly and puts a sentinel `None` after the event to signal stream end
  - `Job.to_dict() -> dict` — for `GET /jobs/:id` response (excludes queue)
- [x] 2.3 Create `src/jobs/registry.py`:
  - `JobRegistry` class with `_jobs: dict[str, Job]`
  - `create(kind: str) -> Job` — instantiate Job, store, return
  - `get(job_id: str) -> Job | None`
  - `list() -> list[Job]`
  - `async cleanup_finished(max_age_sec: int = 86400) -> int` — sweep finished jobs older than max_age, return count removed
  - Module-level singleton `_registry: JobRegistry | None`, `get_registry() -> JobRegistry` lazy-init
  - `async start_cleanup_loop(registry, interval_sec=3600)` — background task that calls `cleanup_finished` periodically
- [x] 2.4 Write `scripts/test_jobs_registry.py` — 10/10 passing

## 3. RAG layer: progress callback support

- [x] 3.1 Modify `src/rag/embedder.py::embed`:
  - Add parameter `progress_callback: Callable[[dict], Awaitable[None]] | None = None`
  - After each batch (every 100 texts), if callback set, `await callback({"event": "embedding_progress", "done": i+len(batch), "total": len(texts)})`
  - Existing callers (no callback passed) behave identically
- [x] 3.2 Modify `src/rag/ingest.py::ingest_document`:
  - Add parameter `progress_callback: Callable[[dict], Awaitable[None]] | None = None`
  - Wrap entire body in try/except; on exception, await `cb({"event": "failed", "error": str(exc)})` then re-raise
  - Emit events at each stage (parsing_started, parsing_done with text_length, chunking_done with total_chunks, then call embedder forwarding the callback, then storing, then done with chunks)
  - All callback awaits are no-ops if callback is None
- [x] 3.3 Update `scripts/test_rag_pipeline.py` — not needed; existing path verified via test_ingest_progress.py no-callback case
- [x] 3.4 Write new `scripts/test_ingest_progress.py` — 3/3 passing (full sequence, failed path, backward-compat)

## 4. Files REST

- [x] 4.1 Create `src/api/files.py`:
  - `router = APIRouter(dependencies=[Depends(require_api_key)])`
  - `POST /projects/{project_id}/files` — accept `UploadFile`, stream to temp, call `files.manager.upload`, return `FileOut`
  - `GET /projects/{project_id}/files` — list `FileOut`
  - `DELETE /projects/{project_id}/files/{file_id}` — 204 or 404
  - Pydantic response model `FileOut(id, project_id, filename, file_type, file_size, parsed, chunk_count, created_at)`
- [x] 4.2 Write `scripts/test_rest_files.py` (PG required) — 21/21 passing:
  - upload → 200 + Document fields
  - list includes uploaded file
  - delete → 204, list excludes it
  - delete missing → 404
  - invalid extension → 400 with ValueError message
  - missing / wrong / correct API key → 401 / 401 / 200

## 5. Knowledge REST + ingest job wiring

- [x] 5.1 Create `src/api/knowledge.py`:
  - `router = APIRouter(dependencies=[Depends(require_api_key)])`
  - `POST /projects/{project_id}/files/{file_id}/ingest` — validates doc, creates Job, spawns `asyncio.create_task(_run_ingest(...))` where the callback wraps `job.emit`, returns 202 `{job_id}`
  - `GET /projects/{project_id}/files/{file_id}/chunks?offset=0&limit=20` — validated via `Query(ge=..., le=...)`, returns `{items, total, offset, limit}`
  - `GET /projects/{project_id}/knowledge/status` — aggregates `file_count`, `parsed_count`, `total_chunks`
- [x] 5.2 Write `scripts/test_rest_knowledge.py` (PG required) — 24/24 passing:
  - POST ingest → 202 + job_id, poll registry until `done`
  - GET chunks paginated + page-2 offset honored
  - `limit=200` → 422, `offset=-1` → 422
  - missing-file chunks / ingest → 404
  - status before/after ingest matches

## 6. Jobs REST + SSE stream

- [x] 6.1 Create `src/api/jobs.py`:
  - `router = APIRouter(prefix="/jobs", dependencies=[Depends(require_api_key)])`
  - `GET /{job_id}` — returns `job.to_dict()` or 404
  - `GET /{job_id}/stream` — `StreamingResponse` with `media_type=text/event-stream`; replay last_event for already-finished jobs; otherwise loop on `asyncio.wait_for(job.queue.get(), timeout=30s)` — timeout → heartbeat frame, sentinel `None` → close; `request.is_disconnected()` checked each iteration
- [x] 6.2 Write `scripts/test_rest_jobs.py` — 23/23 passing:
  - GET returns last_event, status transitions
  - API key enforcement
  - Live SSE: driver emits 5 events → stream yields 5 frames in order ending in `done`
  - Finished-job replay: emit done before connect → stream yields single replay frame
  - Failed-job replay: `failed` + error preserved
  - Missing job → 404

## 7. Wiring

- [x] 7.1 Modify `src/main.py`:
  - Import `files_router`, `knowledge_router`, `jobs_router`
  - In lifespan: `jobs_registry = get_jobs_registry()` → `jobs_cleanup_task = asyncio.create_task(start_jobs_cleanup_loop(jobs_registry))`; on shutdown cancel it alongside the other background tasks
  - `api_router.include_router(files_router / knowledge_router / jobs_router)`
- [x] 7.2 Smoke test: `python src/main.py` (uvicorn under SelectorEventLoop), curl:
  - `/health` → 200
  - `/api/projects/1/files` → 200
  - `/api/projects/1/knowledge/status` → 200 `{"file_count":0,"parsed_count":0,"total_chunks":0}`
  - `/api/jobs/nonexistent` → 404

## 8. Spec sync and archive

- [x] 8.1 Run `openspec validate add-files-knowledge-rest --strict`
- [x] 8.2 Update `progress.md` with summary of new endpoints + test counts
- [ ] 8.3 After user sign-off and all tests green: `openspec archive add-files-knowledge-rest`
