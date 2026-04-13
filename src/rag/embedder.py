"""Text embedding: call OpenAI-compatible embedding API with batching.

Reads `settings.embedding.*` directly and does NOT look up `settings.providers`,
so a chat-only LLM proxy configured on the openai provider cannot poison RAG.

Failures surface as typed exceptions derived from `EmbeddingError` so callers
can degrade gracefully (agent tool) or surface structured errors (REST ingest).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import text

from src.db import get_db
from src.project.config import get_settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100

ProgressCallback = Callable[[dict], Awaitable[None]]


class EmbeddingError(Exception):
    """Base class for embedding failures."""

    def __init__(self, reason: str, api_base: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.api_base = api_base


class EmbeddingUnreachableError(EmbeddingError):
    """Network-level failure reaching the embedding endpoint."""


class EmbeddingAuthError(EmbeddingError):
    """Auth failure (401/403) from the embedding endpoint."""


class EmbeddingAPIError(EmbeddingError):
    """Other non-2xx response from the embedding endpoint."""

    def __init__(self, reason: str, api_base: str = "", status_code: int = 0) -> None:
        super().__init__(reason, api_base)
        self.status_code = status_code


class EmbeddingDimensionMismatchError(EmbeddingError):
    """Configured dimension disagrees with DB column or endpoint output."""

    def __init__(
        self,
        reason: str,
        api_base: str = "",
        configured_dim: int = 0,
        observed_dim: int = 0,
    ) -> None:
        super().__init__(reason, api_base)
        self.configured_dim = configured_dim
        self.observed_dim = observed_dim
        self.remediation = "python scripts/migrate_embedding_dim.py --yes"


_dim_check_ok = False


async def _ensure_db_dim_matches(configured_dim: int, api_base: str) -> None:
    """Query pgvector column dim once per process; cache on success."""
    global _dim_check_ok
    if _dim_check_ok:
        return

    async with get_db() as session:
        result = await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'document_chunks'::regclass "
                "AND attname = 'embedding'"
            )
        )
        row = result.first()

    if row is None:
        raise EmbeddingDimensionMismatchError(
            reason="document_chunks.embedding column not found",
            api_base=api_base,
            configured_dim=configured_dim,
            observed_dim=0,
        )

    db_dim = int(row[0])
    if db_dim != configured_dim:
        raise EmbeddingDimensionMismatchError(
            reason=(
                f"db column is Vector({db_dim}) but settings.embedding.dimensions="
                f"{configured_dim}. Run: python scripts/migrate_embedding_dim.py --yes"
            ),
            api_base=api_base,
            configured_dim=configured_dim,
            observed_dim=db_dim,
        )

    _dim_check_ok = True


def _reset_dim_cache() -> None:
    """Test helper: reset the per-process dim-check cache."""
    global _dim_check_ok
    _dim_check_ok = False


async def embed(
    texts: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
) -> list[list[float]]:
    """Embed a list of texts using the configured embedding model.

    Batches requests to avoid exceeding API limits (max 100 per batch).

    Raises:
        EmbeddingUnreachableError: TCP/DNS failure
        EmbeddingAuthError: 401/403 from the endpoint
        EmbeddingDimensionMismatchError: configured dim != DB column or endpoint output
        EmbeddingAPIError: other non-2xx response
    """
    if not texts:
        return []

    settings = get_settings()
    model = settings.embedding.model
    api_base = settings.embedding.api_base.rstrip("/")
    api_key = settings.embedding.api_key
    configured_dim = settings.embedding.dimensions

    await _ensure_db_dim_matches(configured_dim, api_base)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    all_vectors: list[list[float]] = []
    total = len(texts)

    try:
        async with httpx.AsyncClient(
            base_url=api_base,
            headers=headers,
            timeout=60.0,
        ) as client:
            for i in range(0, total, _BATCH_SIZE):
                batch = texts[i : i + _BATCH_SIZE]
                try:
                    resp = await client.post(
                        "/embeddings",
                        json={"model": model, "input": batch},
                    )
                except httpx.ConnectError as exc:
                    raise EmbeddingUnreachableError(
                        reason=f"cannot reach {api_base}: {exc}",
                        api_base=api_base,
                    ) from exc
                except httpx.TimeoutException as exc:
                    raise EmbeddingUnreachableError(
                        reason=f"timeout reaching {api_base}: {exc}",
                        api_base=api_base,
                    ) from exc

                if resp.status_code in (401, 403):
                    raise EmbeddingAuthError(
                        reason=f"auth failed ({resp.status_code}), check settings.embedding.api_key",
                        api_base=api_base,
                    )
                if resp.status_code != 200:
                    raise EmbeddingAPIError(
                        reason=f"HTTP {resp.status_code}: {resp.text[:500]}",
                        api_base=api_base,
                        status_code=resp.status_code,
                    )

                data = resp.json()
                embeddings = sorted(data["data"], key=lambda x: x["index"])
                batch_vectors = [e["embedding"] for e in embeddings]

                for vec in batch_vectors:
                    if len(vec) != configured_dim:
                        raise EmbeddingDimensionMismatchError(
                            reason=(
                                f"endpoint returned vector of length {len(vec)} "
                                f"but settings.embedding.dimensions={configured_dim}"
                            ),
                            api_base=api_base,
                            configured_dim=configured_dim,
                            observed_dim=len(vec),
                        )

                all_vectors.extend(batch_vectors)

                if progress_callback is not None:
                    await progress_callback(
                        {
                            "event": "embedding_progress",
                            "done": min(i + _BATCH_SIZE, total),
                            "total": total,
                        }
                    )
    except EmbeddingError:
        raise
    except httpx.HTTPError as exc:
        raise EmbeddingUnreachableError(
            reason=f"transport error: {exc}",
            api_base=api_base,
        ) from exc

    return all_vectors
