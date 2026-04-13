## Why

The current embedding code couples to the chat provider config block (`settings.providers.openai`), so any chat-side LLM proxy that lacks a `/embeddings` endpoint silently breaks RAG. Users also have no clean way to run the project without a pre-configured embedding service — there is no graceful degradation, and no supported path for plugging in a local ollama instance or their own external embedding API.

## What Changes

- **Decouple** `embedding` config from `providers.*`: the `embedding` block gains its own `api_base` / `api_key` / `model` / `dimensions` fields and is read directly, independent of the chat provider.
- **Default to local ollama** in shipped `settings.yaml`: `api_base: http://localhost:11434/v1`, `model: nomic-embed-text`, `dimensions: 768`. Zero-config works if the user has ollama running; otherwise the server still starts.
- **Lazy embedder initialization**: the embedder does not connect at startup. The API, chat, pipelines, and exports all start and run normally even when embedding is unreachable.
- **Graceful degradation on two surfaces**:
  - Agent `search_docs` tool: on embedding failure, returns "no results / RAG unavailable" and the agent continues. No exception bubbles out.
  - REST `/files` ingest + knowledge endpoints: on embedding failure, return HTTP 503 with a clear, actionable error (unreachable / auth / dim mismatch) so the user knows exactly what to fix.
- **Dimension safety**: on startup the embedder reads `settings.embedding.dimensions` and compares it against the `document_chunks.embedding` column dimension. On mismatch, every ingest request returns 503 with instructions to run the migration helper.
- **Migration helper script** `scripts/migrate_embedding_dim.py`: drops and recreates the `document_chunks.embedding` column at the configured dimension, with a `--yes` flag for non-interactive use. Warns that existing chunks require re-ingest.
- **BREAKING (internal only)**: `src/rag/embedder.py` no longer reads `settings.providers[...]`. Any downstream code that relied on the coupling must switch to `settings.embedding.api_base` / `api_key`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `embedding`: adds requirements for independent embedding config block, lazy init, dimension check, and error-surface behavior (silent for agent tool, 503 for REST ingest).
- `search-docs-tool`: adds requirement that the tool degrades to an empty-result response when the embedding service is unavailable, rather than raising.
- `file-rest-api`: adds requirement that ingest endpoints surface embedding failures as HTTP 503 with structured error payload.
- `knowledge-rest-api`: same 503-on-embedding-failure requirement for knowledge/search endpoints that depend on embeddings.

## Impact

- **Config**: `config/settings.yaml` — `embedding` block extended with `api_base` / `api_key`; defaults change to ollama localhost. Users with existing `settings.local.yaml` overriding `providers.openai.api_base` to a chat-only proxy will now get RAG working out of the box (if they also run ollama) instead of silently failing.
- **Code**:
  - `src/rag/embedder.py` — decoupled config read, lazy client, dimension check, typed exceptions.
  - `src/tools/builtins/search_docs.py` — catch embedding errors, return empty results.
  - `src/rest/files.py` / ingest paths — map embedding errors to 503.
  - `src/rest/knowledge.py` — same 503 mapping.
  - `src/project/config.py` — `EmbeddingSettings` model extended with `api_base` / `api_key`.
- **New files**: `scripts/migrate_embedding_dim.py`.
- **Docs**: README / setup docs updated with the three scenarios (ollama, external API, no RAG).
- **Out of scope**: smoke-test coverage for RAG flow is deferred to a follow-up change (`extend-smoke-rag-coverage`) per the Post-Phase 7 Local Embedding backlog note already in `integration-smoke-tests` spec.
