"""Document ingestion: parse → chunk → embed → store in one pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import delete, select, update

from src.db import get_db
from src.files.manager import UPLOADS_DIR
from src.models import Document, DocumentChunk
from src.rag.chunker import chunk_text
from src.rag.embedder import embed
from src.rag.parser import parse_document

logger = logging.getLogger(__name__)


async def ingest_document(project_id: int, doc_id: int) -> int:
    """Ingest a document: parse → chunk → embed → store chunks → update Document.

    Returns the number of chunks created.
    """
    # 1. Get the document record
    async with get_db() as session:
        result = await session.execute(
            select(Document).where(
                Document.id == doc_id, Document.project_id == project_id
            )
        )
        doc = result.scalars().first()
        if doc is None:
            raise ValueError(f"Document not found: project_id={project_id}, doc_id={doc_id}")

        file_path = doc.file_path
        file_type = doc.file_type

    # 2. Parse the document
    images_dir = UPLOADS_DIR / str(project_id) / "images" / str(doc_id)
    parse_result = parse_document(file_path, file_type, images_dir=images_dir)

    if not parse_result.text.strip():
        logger.warning("Document %d has no text content after parsing", doc_id)
        return 0

    # 3. Chunk the text
    chunks = chunk_text(
        parse_result.text,
        base_metadata={"doc_id": doc_id, "project_id": project_id},
    )

    if not chunks:
        return 0

    # 4. Embed all chunks
    texts = [c.content for c in chunks]
    vectors = await embed(texts)

    # 5. Delete old chunks (re-ingest support) and insert new ones
    async with get_db() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
        )

        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            db_chunk = DocumentChunk(
                doc_id=doc_id,
                chunk_index=i,
                content=chunk.content,
                embedding=vector,
                metadata_=chunk.metadata,
            )
            session.add(db_chunk)

        # 6. Update the Document record
        await session.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(parsed=True, chunk_count=len(chunks))
        )

    logger.info("Ingested document %d: %d chunks", doc_id, len(chunks))
    return len(chunks)
