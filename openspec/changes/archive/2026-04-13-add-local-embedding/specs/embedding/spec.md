## ADDED Requirements

### Requirement: Embedding config is independent of chat provider config

The `embedding` settings block SHALL contain `api_base`, `api_key`, `model`, `provider`, and `dimensions` fields. The embedder SHALL read these fields directly and SHALL NOT look up `settings.providers[...]`. The `provider` field is retained for telemetry and logging only; runtime behavior is driven by `api_base` and `api_key`.

#### Scenario: Chat proxy does not poison embedding
- **WHEN** `settings.providers.openai.api_base` points at a chat-only proxy that lacks a `/embeddings` endpoint and `settings.embedding.api_base` points at `http://localhost:11434/v1`
- **THEN** the embedder SHALL call `http://localhost:11434/v1/embeddings` and SHALL NOT call the chat proxy

#### Scenario: Default shipped config targets local ollama
- **WHEN** a developer starts the stack with no `settings.local.yaml` overrides
- **THEN** `settings.embedding.api_base` SHALL resolve to `http://localhost:11434/v1` and `settings.embedding.model` SHALL resolve to `nomic-embed-text`

#### Scenario: External embedding API via user config
- **WHEN** a user sets `settings.embedding.api_base` to `https://api.openai.com/v1`, `api_key` to a valid key, `model` to `text-embedding-3-small`, and `dimensions` to `1536`
- **THEN** the embedder SHALL call the external endpoint using the configured key and SHALL return 1536-dimension vectors

### Requirement: Embedder uses lazy initialization and does not block server startup

The embedder SHALL NOT create an HTTP client or probe the embedding endpoint at module import or server startup. The HTTP client SHALL be created on the first `embed()` call. Server startup SHALL succeed even when the configured embedding endpoint is unreachable, misconfigured, or missing auth.

#### Scenario: Server starts with no embedding service running
- **WHEN** the API server starts and nothing is listening on the configured `embedding.api_base`
- **THEN** the server SHALL report healthy on `/health` and all non-RAG endpoints SHALL function normally

#### Scenario: First embed call triggers client creation
- **WHEN** `embed(texts)` is called for the first time after server startup
- **THEN** the embedder SHALL create its HTTP client at that moment and issue the configured request

### Requirement: Embedder raises typed exceptions for failure categories

Embedding failures SHALL raise one of four typed exceptions derived from a common `EmbeddingError` base:
- `EmbeddingUnreachableError` — DNS, TCP, or connection refused
- `EmbeddingAuthError` — HTTP 401 or 403 response from the endpoint
- `EmbeddingDimensionMismatchError` — configured `dimensions` disagrees with the `document_chunks.embedding` column or with the vector length returned by the endpoint
- `EmbeddingAPIError` — any other non-2xx response

Each exception SHALL include the configured `api_base` and a human-readable `reason` attribute.

#### Scenario: Unreachable endpoint
- **WHEN** `embed()` is called and TCP connection to `api_base` fails
- **THEN** the embedder SHALL raise `EmbeddingUnreachableError` with `reason` describing the connection failure and `api_base` populated

#### Scenario: Auth failure
- **WHEN** the endpoint returns HTTP 401
- **THEN** the embedder SHALL raise `EmbeddingAuthError`

#### Scenario: Server error
- **WHEN** the endpoint returns HTTP 500
- **THEN** the embedder SHALL raise `EmbeddingAPIError` carrying the status code and response body

### Requirement: Embedder validates dimension against database schema

Before writing any embedding to `document_chunks`, the embedder SHALL verify that `settings.embedding.dimensions` matches the actual `document_chunks.embedding` column dimension and the vector length returned by the endpoint. On any disagreement, it SHALL raise `EmbeddingDimensionMismatchError` and SHALL NOT write partial data.

#### Scenario: Configured dimension disagrees with column
- **WHEN** `settings.embedding.dimensions=768` and the `document_chunks.embedding` column is `Vector(1536)`
- **THEN** the first `embed()` call SHALL raise `EmbeddingDimensionMismatchError` whose message names `scripts/migrate_embedding_dim.py` as the remediation

#### Scenario: Endpoint returns wrong vector length
- **WHEN** `settings.embedding.dimensions=768` and the endpoint returns 1024-length vectors
- **THEN** the embedder SHALL raise `EmbeddingDimensionMismatchError` referencing both the configured and returned dimensions

### Requirement: Dimension migration helper script

The system SHALL provide `scripts/migrate_embedding_dim.py` that reads `settings.embedding.dimensions` and reshapes the `document_chunks.embedding` column to match. The script SHALL require either interactive confirmation or a `--yes` flag before any destructive operation, and SHALL print a reminder that existing chunks must be re-ingested.

#### Scenario: Interactive confirmation required by default
- **WHEN** a user runs `python scripts/migrate_embedding_dim.py` without `--yes`
- **THEN** the script SHALL prompt for confirmation and SHALL abort if the user does not type `yes`

#### Scenario: Non-interactive migration
- **WHEN** a user runs `python scripts/migrate_embedding_dim.py --yes` with `settings.embedding.dimensions=768`
- **THEN** the script SHALL drop and recreate `document_chunks.embedding` as `Vector(768)`, print a re-ingest reminder, and exit 0

## MODIFIED Requirements

### Requirement: Embedding uses configured model and provider

embed SHALL read `settings.embedding.model`, `settings.embedding.api_base`, `settings.embedding.api_key`, and `settings.embedding.dimensions` to configure API calls. The `settings.embedding.provider` field is retained for telemetry only and SHALL NOT be used to look up any other config block.

#### Scenario: OpenAI-compatible embedding endpoint
- **WHEN** `settings.embedding.api_base` is any OpenAI-compatible base URL
- **THEN** embed SHALL POST to `{api_base}/embeddings` with `Authorization: Bearer {api_key}` (omitted if `api_key` is empty) and SHALL parse the response as an OpenAI-format embeddings response

#### Scenario: Dimensions match configuration
- **WHEN** embed returns vectors
- **THEN** each vector length SHALL equal `settings.embedding.dimensions` or embed SHALL raise `EmbeddingDimensionMismatchError`
