"""REST endpoints for project file management (upload, list, delete)."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.api.auth import require_api_key
from src.files import manager as files_manager
from src.models import Document

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


class FileOut(BaseModel):
    id: int
    project_id: int
    filename: str
    file_type: str
    file_size: int | None
    parsed: bool
    chunk_count: int
    created_at: datetime | None


def _to_out(doc: Document) -> FileOut:
    return FileOut(
        id=doc.id,
        project_id=doc.project_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        parsed=doc.parsed,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at,
    )


@router.post(
    "/projects/{project_id}/files",
    response_model=FileOut,
    status_code=200,
)
async def upload_file(project_id: int, file: UploadFile = File(...)) -> FileOut:
    """Upload a file: stream to a temp path, then hand off to files.manager.upload."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")

    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        try:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                tmp.write(chunk)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    # Rename to preserve the original filename so manager.upload uses it.
    final_tmp = tmp_path.parent / file.filename
    try:
        tmp_path.rename(final_tmp)
    except OSError:
        # Cross-volume or name conflict — fall back to copy.
        import shutil

        shutil.move(str(tmp_path), str(final_tmp))

    try:
        doc = await files_manager.upload(project_id, final_tmp)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        final_tmp.unlink(missing_ok=True)

    return _to_out(doc)


@router.get("/projects/{project_id}/files", response_model=list[FileOut])
async def list_files(project_id: int) -> list[FileOut]:
    docs = await files_manager.list_files(project_id)
    return [_to_out(d) for d in docs]


@router.delete(
    "/projects/{project_id}/files/{file_id}",
    status_code=204,
)
async def delete_file(project_id: int, file_id: int) -> None:
    doc = await files_manager.delete_file(project_id, file_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="file not found")
    return None
