"""Verification for file manager: upload, format validation, list, delete, get_file_path."""

import asyncio
import os
import shutil
import sys
import tempfile

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from src.files.manager import UPLOADS_DIR, delete_file, get_file_path, list_files, upload
from src.models import Document

# Assumes default user id=1 and we create a test project
TEST_USER_ID = 1
TEST_PROJECT_ID = None  # set after creating project


async def setup_test_project() -> int:
    """Create a test project, return its id."""
    from src.project.manager import create_project

    project = await create_project(
        user_id=TEST_USER_ID,
        name="File Test Project",
        pipeline="test",
    )
    return project.id


async def test_upload_valid(project_id: int):
    print("=== upload: valid file ===")

    # Create a temp .md file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Test Document\n\nHello world.")
        tmp_path = f.name

    try:
        doc = await upload(project_id, tmp_path)

        assert isinstance(doc, Document)
        assert doc.id > 0
        assert doc.project_id == project_id
        assert doc.file_type == "md"
        assert doc.parsed is False
        assert doc.chunk_count == 0
        assert doc.file_size > 0

        # Check physical file exists
        assert Path(doc.file_path).exists(), f"File should exist at {doc.file_path}"

        print(f"  uploaded: id={doc.id}, filename={doc.filename}, size={doc.file_size}")
        print(f"  file_path: {doc.file_path}")
        print("  OK")
        return doc
    finally:
        os.unlink(tmp_path)


async def test_upload_invalid_type(project_id: int):
    print("=== upload: invalid file type ===")

    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
        f.write(b"fake exe")
        tmp_path = f.name

    try:
        await upload(project_id, tmp_path)
        print("  FAIL: expected ValueError")
    except ValueError as e:
        assert "not supported" in str(e)
        print(f"  ValueError: {e}")
        print("  OK")
    finally:
        os.unlink(tmp_path)


async def test_list_files(project_id: int, expected_count: int):
    print("=== list_files ===")
    docs = await list_files(project_id)

    assert isinstance(docs, list)
    assert len(docs) == expected_count, f"Expected {expected_count}, got {len(docs)}"
    for d in docs:
        assert d.project_id == project_id

    print(f"  found {len(docs)} document(s)")
    print("  OK")


async def test_get_file_path(project_id: int, doc_id: int, expected_path: str):
    print("=== get_file_path ===")

    path = await get_file_path(project_id, doc_id)
    assert path == expected_path, f"Expected {expected_path}, got {path}"
    print(f"  path: {path}")

    # Not found
    result = await get_file_path(project_id, 99999)
    assert result is None
    print("  non-existent -> None: OK")

    print("  OK")


async def test_delete_file(project_id: int, doc_id: int, file_path: str):
    print("=== delete_file ===")

    assert Path(file_path).exists(), "File should exist before delete"

    doc = await delete_file(project_id, doc_id)
    assert doc is not None
    assert doc.id == doc_id
    print(f"  deleted: id={doc.id}")

    # Physical file removed
    assert not Path(file_path).exists(), "File should be removed after delete"
    print("  physical file removed: OK")

    # DB record gone
    docs = await list_files(project_id)
    ids = [d.id for d in docs]
    assert doc_id not in ids, "Deleted doc should not appear in list"
    print("  excluded from list_files: OK")

    # Delete non-existent
    result = await delete_file(project_id, 99999)
    assert result is None
    print("  non-existent -> None: OK")

    print("  OK")


async def main():
    print("\n--- File Manager Verification ---\n")

    from src.db import close_db, init_db

    await init_db()

    project_id = await setup_test_project()
    print(f"Test project id: {project_id}\n")

    try:
        doc = await test_upload_valid(project_id)
        await test_upload_invalid_type(project_id)
        await test_list_files(project_id, expected_count=1)
        await test_get_file_path(project_id, doc.id, doc.file_path)
        await test_delete_file(project_id, doc.id, doc.file_path)
        await test_list_files(project_id, expected_count=0)
    finally:
        # Cleanup uploads directory for test project
        test_uploads = UPLOADS_DIR / str(project_id)
        if test_uploads.exists():
            shutil.rmtree(test_uploads)
            print(f"\n  Cleaned up: {test_uploads}")
        await close_db()

    print("\n[PASS] All file manager tests passed!\n")


if __name__ == "__main__":
    # Windows: psycopg requires SelectorEventLoop
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
