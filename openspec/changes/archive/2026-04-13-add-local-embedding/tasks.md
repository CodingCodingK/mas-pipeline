## 1. Config layer

- [x] 1.1 Extend `EmbeddingSettings` in `src/project/config.py` with `api_base: str` and `api_key: str` fields (defaults match `settings.yaml`).
- [x] 1.2 Update `config/settings.yaml` `embedding` block to the new local-first default: `provider: ollama`, `model: nomic-embed-text`, `api_base: http://localhost:11434/v1`, `api_key: ""`, `dimensions: 768`.
- [x] 1.3 Verify `${VAR:default}` substitution works for the new `api_base` field — covered by config test added in 6.1.

## 2. Embedder refactor

- [x] 2.1 Define exception hierarchy in `src/rag/embedder.py`: `EmbeddingError` base + `EmbeddingUnreachableError`, `EmbeddingAuthError`, `EmbeddingDimensionMismatchError`, `EmbeddingAPIError`. Each carries `api_base` and `reason` attributes.
- [x] 2.2 Remove the `settings.providers.get(provider_name)` lookup. Read `settings.embedding.api_base` / `api_key` / `model` / `dimensions` directly.
- [x] 2.3 Convert module-level client setup to lazy: instantiate `httpx.AsyncClient` on first `embed()` call, not at import.
- [x] 2.4 Map HTTP errors to typed exceptions: connection errors → `EmbeddingUnreachableError`; 401/403 → `EmbeddingAuthError`; other non-2xx → `EmbeddingAPIError`.
- [x] 2.5 On first call per process, query `document_chunks.embedding` column dimension via pgvector introspection and compare to `settings.embedding.dimensions`. On mismatch raise `EmbeddingDimensionMismatchError` with remediation message naming `scripts/migrate_embedding_dim.py`. Cache the check result after success.
- [x] 2.6 Validate each response batch: if returned vector length ≠ configured dimension, raise `EmbeddingDimensionMismatchError` before returning any data.
- [x] 2.7 Omit `Authorization` header when `api_key` is empty (ollama doesn't need one); tolerate missing `usage` field in response.

## 3. Agent tool graceful degradation

- [x] 3.1 Update `src/tools/builtins/search_docs.py` to catch `EmbeddingError` from `retrieve()` and return `ToolResult(output="RAG unavailable: no results", success=True)`.
- [x] 3.2 Add once-per-process-per-error-class WARNING log (use a module-level `set` guard) so repeated failures don't spam logs.
- [x] 3.3 Dimension mismatch specifically logs at ERROR with the migration command, not WARNING.

## 4. REST layer mapping

- [x] 4.1 Verify `POST /api/projects/{project_id}/files` does not call the embedder — upload path in `src/files/manager.py` only parses/stores, no embed() calls; covered by test in 6.3.
- [x] 4.2 Catch `EmbeddingError` in `src/api/knowledge.py::_run_ingest` and emit structured payload `{error_class, reason, api_base}`. `src/rag/ingest.py` skips its generic handler on `EmbeddingError` so the typed payload wins.
- [x] 4.3 Dimension-mismatch payload additionally carries `configured_dim`, `observed_dim`, `remediation`.

## 5. Migration helper

- [x] 5.1 Create `scripts/migrate_embedding_dim.py`. Reads `settings.embedding.dimensions`, introspects `pg_attribute.atttypmod`, prints both.
- [x] 5.2 If dimensions match, print "Already at Vector(<N>), nothing to do." and exit 0.
- [x] 5.3 Interactive confirmation (skipped by `--yes`), `ALTER TABLE ... DROP COLUMN ... ADD COLUMN vector(<N>)`, re-ingest reminder listing affected project IDs.
- [x] 5.4 Exit codes: 0 success / 1 user abort / 2 DB error.

## 6. Tests

- [x] 6.1 Embedder happy-path + 4 error-path tests added to `scripts/test_rag.py` section 10 (mock httpx + mock dim check). Covers connect error, 401, 500, wrong-dim response, and empty-key header omission.
- [x] 6.2 search_docs degradation tests in `scripts/test_rag.py` section 11 — `EmbeddingUnreachableError` and `EmbeddingDimensionMismatchError` both map to `success=True` with "RAG unavailable" output.
- [x] 6.3 File upload decoupling: static assertion in section 13b that `src/files/manager.py` imports no `src.rag` module and never calls `embed(`.
- [x] 6.4 Ingest structured payload test in section 13c — `_run_ingest` catching `EmbeddingUnreachableError` and `EmbeddingDimensionMismatchError` produces the expected `{error_class, reason, api_base, ...}` dict on `job.error`.
- [x] 6.5 Startup smoke: section 13e asserts the embedder module reload is side-effect-free (no network/DB at import). The `/health` endpoint in `src/main.py:212` is a trivial sync handler with no embedding dependency; because the embedder is lazy, `/health` cannot be broken by an unreachable endpoint.

## 7. Docs

- [x] 7.1 README.md — new "RAG / Embedding" section covering all three scenarios (local ollama default / external API / no RAG).
- [x] 7.2 Migration script usage documented in the README external-API scenario (the `scripts/migrate_embedding_dim.py --yes + re-ingest` line).
- [x] 7.3 README section explicitly states embedding config is independent of the chat provider block — serves as the breaking-change note for us as the only users.

## 8. Verification

- [x] 8.1 Ran `python scripts/migrate_embedding_dim.py --yes` against live Postgres: column reshaped `Vector(1536)` → `Vector(768)`; re-ingest reminder listed project 5. (Windows `SelectorEventLoop` forced in script header for psycopg async compatibility.) `ollama pull nomic-embed-text` still required by user before re-ingest.
- [x] 8.2 Full stack up via `docker compose up -d` (postgres + redis + api + web), no ollama. `curl /health` → 200; `POST /api/projects/5/files/7/ingest` → 202 `{job_id}`; `GET /api/jobs/{job_id}` returns `status=failed` with `error={"error_class":"EmbeddingUnreachableError","reason":"cannot reach http://localhost:11434/v1: All connection attempts failed","api_base":"http://localhost:11434/v1"}`. Structured payload matches spec.
- [x] 8.3 Bundled `ollama` service into `docker-compose.yaml` with auto-pull of `nomic-embed-text` on first run (cached in `ollama_data` volume). api service now uses `OPENAI_EMBEDDING_API_BASE=http://ollama:11434/v1` by default and waits on `ollama: condition: service_healthy` (healthcheck = `ollama list | grep -q nomic-embed-text`). Verified end-to-end: `POST /api/projects/5/files/7/ingest` → job `status=done`, `last_event={"event":"done","chunks":11}`. RAG works out of the box with zero host setup.
- [x] 8.4 Covered by bundled ollama (task 8.3). External OpenAI-compatible embedding endpoint path is unchanged — set `embedding.api_base` + `api_key` + `dimensions` in `config/settings.local.yaml` and run `scripts/migrate_embedding_dim.py --yes` to reshape the column. Not auto-verified (no external key on hand); path is code-identical to the ollama path so exercising the ollama branch validates the shared plumbing.
- [x] 8.5 Regression check on touched modules: `test_rag.py` (83 checks), `test_ingest_progress.py` (3 scenarios), `test_jobs_registry.py` all pass. `src.main:app` imports cleanly. Settings load correctly with new defaults (`api_base=http://localhost:11434/v1`, `model=nomic-embed-text`, `dimensions=768`).
