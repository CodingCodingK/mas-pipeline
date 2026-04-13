## Context

RAG currently breaks in any developer environment whose `settings.local.yaml` points `providers.openai.api_base` at a chat-only LLM proxy (e.g., `codex-for.me`). The reason is a config coupling: `src/rag/embedder.py` reads `settings.embedding.provider` and then looks up `settings.providers[provider_name]` — so embedding inherits the chat provider's `api_base`/`api_key` whether that endpoint speaks `/embeddings` or not. When the proxy returns 404 for embeddings, every file upload fails noisily and the entire project appears broken.

The project must ship a default that Just Works for most developers (ollama on localhost) while still letting users plug in their own external embedding API, and must **not** require an embedding service to be up for the server to start at all. RAG is a feature, not a dependency of the core pipeline.

## Goals / Non-Goals

**Goals:**
- Decouple embedding config from chat provider config so chat-side proxies can't poison RAG.
- Ship a zero-config default (ollama + `nomic-embed-text`, 768 dims) that works if the user runs `ollama serve`.
- Support a user-configured external embedding API (OpenAI, Azure, self-hosted, etc.) via a single `settings.embedding.*` block.
- Graceful degradation: API/chat/pipelines/exports work end-to-end even when embedding is unreachable; only RAG-dependent surfaces fail.
- Two distinct failure surfaces: agent `search_docs` degrades silently, REST ingest returns structured 503.
- Safe dimension changes: on startup detect schema/config mismatch, give a clear migration path, never silently corrupt data.

**Non-Goals:**
- Per-request dynamic dimension — pgvector column dimension is schema-level and a clean dynamic column adds no value over "configure once + migrate".
- Bundling an embedding model — users install ollama or point at their API.
- Adding smoke-test coverage for the RAG flow. Deferred to follow-up change `extend-smoke-rag-coverage`.
- Re-ingest automation. The migration helper drops the column; users must re-upload or re-run existing ingest jobs themselves.

## Decisions

### Decision 1: `embedding` gets its own api_base / api_key, independent of `providers.*`

**Chosen:** Add `api_base` and `api_key` fields directly to the `embedding` block. `src/rag/embedder.py` reads them directly. No lookup into `settings.providers`.

**Alternative considered:** Add a dedicated `providers.embedding` sub-entry. Rejected — introduces a second "providers-like" structure and still couples via naming convention. One block for one concern is simpler.

**Shipped default:**
```yaml
embedding:
  provider: ollama            # kept for telemetry/logging only; behavior driven by api_base
  model: nomic-embed-text
  api_base: http://localhost:11434/v1
  api_key: ""
  dimensions: 768
```

Ollama's `/v1/embeddings` endpoint is OpenAI-compatible, so the same `OpenAIEmbeddingClient` handles both ollama and any real OpenAI-compatible API without branching.

### Decision 2: Lazy init, never block startup

**Chosen:** `Embedder` is instantiated at import time but does **not** create an HTTP client or probe the API until the first `embed()` call. Startup never touches the embedding endpoint.

**Why:** A developer who just wants to poke the chat UI should not be forced to run ollama. Also matches the existing lazy-init pattern used for LLM adapters.

### Decision 3: Two failure surfaces — silent for agent tool, 503 for REST

**Chosen:**

| Caller | Failure mode | Rationale |
|---|---|---|
| `search_docs` agent tool | Returns `ToolResult(output="RAG unavailable: no results", success=True)` | Agent is *exploring* — missing data shouldn't crash the run |
| `POST /files/{id}/ingest` | Job transitions to `failed` with structured error; endpoint still returns 202 first (job-based) | Ingest is already async via Job; failure surface is the Job |
| `GET /knowledge/status` | 200 (aggregates from DB, no embedding call) | No change |
| Direct synchronous embedding (if any new endpoint adds it) | 503 with `{error: "embedding_unavailable", reason: ...}` | User asked explicitly — tell them |

**Typed exceptions** define the mapping:
- `EmbeddingUnreachableError` — TCP/DNS failure
- `EmbeddingAuthError` — 401/403 from endpoint
- `EmbeddingDimensionMismatchError` — configured vs DB column disagreement
- `EmbeddingAPIError` — catch-all for other 4xx/5xx

REST layer catches these and maps to 503 with the error class name in the payload; `search_docs` catches the base `EmbeddingError` and swallows.

### Decision 4: Static dimension with startup check + migration helper

**Chosen:** `settings.embedding.dimensions` is the authoritative config value. On the first `embed()` call (or optionally at startup as a cheap DB query), the embedder executes `SELECT atttypmod FROM pg_attribute` (or equivalent pgvector introspection) on `document_chunks.embedding`, compares it to the configured dimension, and if they disagree raises `EmbeddingDimensionMismatchError` with a message pointing at the migration script.

**Migration helper:** `scripts/migrate_embedding_dim.py`:
1. Reads `settings.embedding.dimensions`.
2. Confirms destructive intent (requires `--yes` for non-interactive).
3. Drops `document_chunks.embedding` column and recreates at the new dim.
4. Prints a re-ingest reminder listing affected projects.

**Alternatives considered:**
- Dynamic `Vector` column (no fixed dim): supported by pgvector but blocks index creation and tanks query speed. Rejected.
- Auto-migrate on startup: one typo in `settings.local.yaml` destroys all chunks. Too dangerous.
- Multiple vector columns per dim: massive schema bloat, hard to query. Rejected.

### Decision 5: Graceful degradation for missing ollama — default config stays, errors stay quiet

**Chosen:** Shipped default points at `http://localhost:11434/v1`. If ollama is not running, the first call fails with `EmbeddingUnreachableError`. The agent tool swallows it, the Job marks failed. The **server and all non-RAG features are unaffected**. Logs show a single `INFO: embedding unavailable, RAG disabled` line — not a stack trace flood.

## Risks / Trade-offs

- **[Risk]** Users with existing `settings.local.yaml` that relied on embedding inheriting from `providers.openai` will see RAG stop using that endpoint. → **Mitigation:** release note calls this out; migration is a two-line diff (copy api_base/api_key into the embedding block).
- **[Risk]** Dimension mismatch check adds a DB round-trip on the first embed call. → **Mitigation:** cached after first call; negligible cost.
- **[Risk]** Ollama's OpenAI-compatible endpoint has occasional quirks (e.g., missing `usage` field). → **Mitigation:** client treats `usage` as optional, tolerates absence.
- **[Risk]** A user swaps embedding models mid-project without running the migration, then every ingest fails. → **Mitigation:** error message names the exact script + flag to run; dimension check runs before any DB write.
- **[Risk]** The default `nomic-embed-text` (768d) differs from the current `text-embedding-3-small` (1536d), so the upgrade requires running the migration script once and re-ingesting existing chunks. → **Mitigation:** project is single-team internal; we accept the one-time migration and re-ingest as part of landing this change.

## Migration Plan

Project is currently single-team internal; we ship the clean default and migrate in one step.

1. Land code + config changes. Shipped `settings.yaml` defaults to `model: nomic-embed-text`, `api_base: http://localhost:11434/v1`, `dimensions: 768`.
2. Run `ollama pull nomic-embed-text` on dev machine.
3. Run `python scripts/migrate_embedding_dim.py --yes` — drops and recreates `document_chunks.embedding` as `Vector(768)`. Existing chunks are gone (acceptable — we own all data).
4. Re-run ingest on any projects that had uploaded files.
5. Rollback: revert the code commit and restore the old column via a second migration run with the old dimensions set. No automated rollback needed — if something goes wrong pre-migration, just revert.
