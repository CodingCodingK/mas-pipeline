"""REST endpoints for project knowledge: ingest jobs, chunk browsing, status."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api.auth import require_api_key
from src.db import get_db
from src.jobs import Job, get_registry
from src.models import Document, DocumentChunk
from src.rag.embedder import EmbeddingDimensionMismatchError, EmbeddingError
from src.rag.ingest import ingest_document

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


class IngestJobOut(BaseModel):
    job_id: str


class ChunkOut(BaseModel):
    chunk_index: int
    content: str
    metadata: dict


class ChunkPage(BaseModel):
    items: list[ChunkOut]
    total: int
    offset: int
    limit: int


class KnowledgeStatus(BaseModel):
    file_count: int
    parsed_count: int
    total_chunks: int


async def _assert_doc_belongs(project_id: int, file_id: int) -> Document:
    async with get_db() as session:
        result = await session.execute(
            select(Document).where(
                Document.id == file_id, Document.project_id == project_id
            )
        )
        doc = result.scalars().first()
    if doc is None:
        raise HTTPException(status_code=404, detail="file not found")
    return doc


def _make_async_emit(job: Job):
    async def _emit(event: dict) -> None:
        job.emit(event)

    return _emit


def _embedding_error_payload(exc: EmbeddingError) -> dict:
    payload: dict = {
        "error_class": type(exc).__name__,
        "reason": exc.reason,
        "api_base": exc.api_base,
    }
    if isinstance(exc, EmbeddingDimensionMismatchError):
        payload["configured_dim"] = exc.configured_dim
        payload["observed_dim"] = exc.observed_dim
        payload["remediation"] = exc.remediation
    return payload


async def _run_ingest(project_id: int, file_id: int, job: Job) -> None:
    emit = _make_async_emit(job)
    try:
        await ingest_document(
            project_id=project_id,
            doc_id=file_id,
            progress_callback=emit,
        )
    except EmbeddingError as exc:
        logger.warning(
            "ingest failed for project=%d file=%d: %s — %s",
            project_id,
            file_id,
            type(exc).__name__,
            exc.reason,
        )
        if job.status not in ("done", "failed"):
            job.emit({"event": "failed", "error": _embedding_error_payload(exc)})
    except Exception as exc:
        logger.exception("ingest failed for project=%d file=%d", project_id, file_id)
        if job.status not in ("done", "failed"):
            job.emit({"event": "failed", "error": str(exc)})


@router.post(
    "/projects/{project_id}/files/{file_id}/ingest",
    response_model=IngestJobOut,
    status_code=202,
)
async def start_ingest(project_id: int, file_id: int) -> IngestJobOut:
    """Kick off an ingest job. Returns immediately with a job_id; progress is
    observable via `GET /jobs/{job_id}` or `GET /jobs/{job_id}/stream`."""
    await _assert_doc_belongs(project_id, file_id)

    registry = get_registry()
    job = registry.create(kind="ingest")
    asyncio.create_task(
        _run_ingest(project_id, file_id, job),
        name=f"ingest-{job.id}",
    )
    return IngestJobOut(job_id=job.id)


@router.get(
    "/projects/{project_id}/files/{file_id}/chunks",
    response_model=ChunkPage,
)
async def list_chunks(
    project_id: int,
    file_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> ChunkPage:
    await _assert_doc_belongs(project_id, file_id)

    async with get_db() as session:
        total_result = await session.execute(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.doc_id == file_id
            )
        )
        total = int(total_result.scalar() or 0)

        rows_result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == file_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = list(rows_result.scalars().all())

    items = [
        ChunkOut(
            chunk_index=r.chunk_index,
            content=r.content,
            metadata=r.metadata_ or {},
        )
        for r in rows
    ]
    return ChunkPage(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/projects/{project_id}/knowledge/status",
    response_model=KnowledgeStatus,
)
async def knowledge_status(project_id: int) -> KnowledgeStatus:
    async with get_db() as session:
        file_count_r = await session.execute(
            select(func.count(Document.id)).where(Document.project_id == project_id)
        )
        parsed_count_r = await session.execute(
            select(func.count(Document.id)).where(
                Document.project_id == project_id, Document.parsed == True  # noqa: E712
            )
        )
        total_chunks_r = await session.execute(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.project_id == project_id
            )
        )

    return KnowledgeStatus(
        file_count=int(file_count_r.scalar() or 0),
        parsed_count=int(parsed_count_r.scalar() or 0),
        total_chunks=int(total_chunks_r.scalar() or 0),
    )
