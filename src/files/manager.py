"""File manager: upload, list, delete, and path lookup for project documents."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import select

from src.db import get_db
from src.models import Document
from src.project.config import ROOT_DIR

logger = logging.getLogger(__name__)

UPLOADS_DIR = ROOT_DIR / "uploads"

ALLOWED_EXTENSIONS = {"pdf", "pptx", "md", "docx", "png", "jpg", "jpeg"}


async def upload(project_id: int, file_path: str | Path) -> Document:
    """Register a file: validate extension, copy to uploads dir, insert DB record."""
    src = Path(file_path)

    # Validate extension
    ext = src.suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type '.{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Copy to uploads directory
    dest_dir = UPLOADS_DIR / str(project_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)

    # Insert DB record
    doc = Document(
        project_id=project_id,
        filename=src.name,
        file_type=ext,
        file_path=str(dest),
        file_size=dest.stat().st_size,
    )
    async with get_db() as session:
        session.add(doc)
        await session.flush()

    return doc


async def list_files(project_id: int) -> list[Document]:
    """List all documents for a project, newest first."""
    async with get_db() as session:
        result = await session.execute(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())


async def delete_file(project_id: int, doc_id: int) -> Document | None:
    """Delete a document record (cascades to chunks) and remove the physical file."""
    async with get_db() as session:
        result = await session.execute(
            select(Document).where(Document.id == doc_id, Document.project_id == project_id)
        )
        doc = result.scalars().first()
        if doc is None:
            return None

        # Remove physical file (best-effort)
        if doc.file_path:
            try:
                Path(doc.file_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to delete physical file: %s", doc.file_path)

        await session.delete(doc)

    return doc


async def get_file_path(project_id: int, doc_id: int) -> str | None:
    """Return the physical file path for a document, or None if not found."""
    async with get_db() as session:
        result = await session.execute(
            select(Document.file_path).where(
                Document.id == doc_id, Document.project_id == project_id
            )
        )
        row = result.first()
        return row[0] if row else None
