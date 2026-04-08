"""Vector retrieval: pgvector cosine similarity search with project isolation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select, text

from src.db import get_db
from src.models import Document, DocumentChunk
from src.rag.embedder import embed

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """A single retrieval result."""

    content: str
    metadata: dict
    score: float
    doc_id: int


async def retrieve(
    project_id: int,
    query: str,
    top_k: int = 5,
) -> list[RetrievalResult]:
    """Retrieve the most relevant document chunks for a query.

    Uses pgvector cosine distance (<=>), filtered by project_id.
    """
    # Embed the query
    vectors = await embed([query])
    if not vectors:
        return []
    query_vector = vectors[0]

    async with get_db() as session:
        # pgvector cosine distance: lower = more similar
        # We join document_chunks with documents to filter by project_id
        stmt = (
            select(
                DocumentChunk.content,
                DocumentChunk.metadata_,
                DocumentChunk.doc_id,
                DocumentChunk.embedding.cosine_distance(query_vector).label("distance"),
            )
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(Document.project_id == project_id)
            .where(DocumentChunk.embedding.is_not(None))
            .order_by("distance")
            .limit(top_k)
        )

        result = await session.execute(stmt)
        rows = result.all()

    return [
        RetrievalResult(
            content=row.content,
            metadata=row.metadata_ or {},
            score=1.0 - row.distance,  # convert distance to similarity
            doc_id=row.doc_id,
        )
        for row in rows
    ]
