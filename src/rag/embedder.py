"""Text embedding: call OpenAI-compatible embedding API with batching."""

from __future__ import annotations

import logging

import httpx

from src.project.config import get_settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using the configured embedding model.

    Batches requests to avoid exceeding API limits (max 100 per batch).
    """
    if not texts:
        return []

    settings = get_settings()
    provider_name = settings.embedding.provider
    provider_cfg = settings.providers.get(provider_name)
    if provider_cfg is None:
        raise ValueError(f"Embedding provider '{provider_name}' not configured")

    model = settings.embedding.model
    api_base = provider_cfg.api_base.rstrip("/")
    api_key = provider_cfg.api_key

    all_vectors: list[list[float]] = []

    async with httpx.AsyncClient(
        base_url=api_base,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=60.0,
    ) as client:
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            resp = await client.post(
                "/embeddings",
                json={"model": model, "input": batch},
            )

            if resp.status_code != 200:
                raise RuntimeError(
                    f"Embedding API error {resp.status_code}: {resp.text[:500]}"
                )

            data = resp.json()
            # Sort by index to ensure order matches input
            embeddings = sorted(data["data"], key=lambda x: x["index"])
            all_vectors.extend([e["embedding"] for e in embeddings])

    return all_vectors
