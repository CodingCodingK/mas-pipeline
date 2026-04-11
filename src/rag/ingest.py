"""Document ingestion: parse → chunk → embed → store in one pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select, update

from src.db import get_db
from src.files.manager import UPLOADS_DIR
from src.models import Document, DocumentChunk
from src.rag.chunker import chunk_text
from src.rag.embedder import embed
from src.rag.parser import parse_document

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], Awaitable[None]]


async def _emit(cb: ProgressCallback | None, event: dict) -> None:
    if cb is not None:
        await cb(event)


async def ingest_document(
    project_id: int,
    doc_id: int,
    *,
    progress_callback: ProgressCallback | None = None,
) -> int:
    """Ingest a document: parse → chunk → embed → store chunks → update Document.

    Returns the number of chunks created.

    If `progress_callback` is provided, it is awaited at each stage with one of:
      {"event": "parsing_started"}
      {"event": "parsing_done", "text_length": int}
      {"event": "chunking_done", "total_chunks": int}
      {"event": "embedding_progress", "done": int, "total": int}  (per batch)
      {"event": "storing"}
      {"event": "done", "chunks": int}
      {"event": "failed", "error": str}                            (on exception, then re-raised)
    """
    try:
        # 1. Get the document record
        await _emit(progress_callback, {"event": "parsing_started"})
        async with get_db() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id, Document.project_id == project_id
                )
            )
            doc = result.scalars().first()
            if doc is None:
                raise ValueError(
                    f"Document not found: project_id={project_id}, doc_id={doc_id}"
                )

            file_path = doc.file_path
            file_type = doc.file_type

        # 2. Parse the document
        images_dir = UPLOADS_DIR / str(project_id) / "images" / str(doc_id)
        parse_result = parse_document(file_path, file_type, images_dir=images_dir)

        if not parse_result.text.strip():
            logger.warning("Document %d has no text content after parsing", doc_id)
            await _emit(progress_callback, {"event": "done", "chunks": 0})
            return 0

        await _emit(
            progress_callback,
            {"event": "parsing_done", "text_length": len(parse_result.text)},
        )

        # 3. Chunk the text
        chunks = chunk_text(
            parse_result.text,
            base_metadata={"doc_id": doc_id, "project_id": project_id},
        )

        if not chunks:
            await _emit(progress_callback, {"event": "done", "chunks": 0})
            return 0

        await _emit(
            progress_callback,
            {"event": "chunking_done", "total_chunks": len(chunks)},
        )

        # 4. Embed all chunks
        texts = [c.content for c in chunks]
        vectors = await embed(texts, progress_callback=progress_callback)

        # 5. Delete old chunks (re-ingest support) and insert new ones
        await _emit(progress_callback, {"event": "storing"})
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
        await _emit(progress_callback, {"event": "done", "chunks": len(chunks)})
        return len(chunks)
    except Exception as exc:
        await _emit(progress_callback, {"event": "failed", "error": str(exc)})
        raise
