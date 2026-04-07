"""Verification for project manager: CRUD, uploads directory, archive soft-delete."""

import asyncio
import os
import shutil
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import Project
from src.project.manager import (
    UPLOADS_DIR,
    archive_project,
    create_project,
    get_project,
    list_projects,
    update_project,
)

# Test user_id — assumes default user id=1 from init_db.sql seed
TEST_USER_ID = 1


async def test_create_project():
    print("=== create_project ===")
    project = await create_project(
        user_id=TEST_USER_ID,
        name="Test Blog Project",
        pipeline="blog_generation",
        description="A test project for blog generation",
        config={"language": "zh"},
    )

    assert isinstance(project, Project), f"Expected Project, got {type(project)}"
    assert project.id > 0, f"Expected positive id, got {project.id}"
    assert project.name == "Test Blog Project"
    assert project.pipeline == "blog_generation"
    assert project.status == "active"
    assert project.config == {"language": "zh"}

    # Check uploads directory was created
    uploads_path = UPLOADS_DIR / str(project.id)
    assert uploads_path.exists(), f"Expected uploads dir at {uploads_path}"
    assert uploads_path.is_dir()

    print(f"  created: id={project.id}, name={project.name}")
    print(f"  uploads dir: {uploads_path} (exists={uploads_path.exists()})")
    print("  OK")
    return project


async def test_get_project(project_id: int):
    print("=== get_project ===")

    # Found
    project = await get_project(project_id, TEST_USER_ID)
    assert project is not None, "Expected to find project"
    assert project.id == project_id
    print(f"  found: id={project.id}, name={project.name}")

    # Not found (wrong user)
    result = await get_project(project_id, user_id=99999)
    assert result is None, "Expected None for wrong user_id"
    print("  wrong user_id -> None: OK")

    # Not found (wrong id)
    result = await get_project(99999, TEST_USER_ID)
    assert result is None, "Expected None for non-existent id"
    print("  non-existent id -> None: OK")

    print("  OK")


async def test_list_projects():
    print("=== list_projects ===")
    projects = await list_projects(TEST_USER_ID)

    assert isinstance(projects, list)
    assert len(projects) > 0, "Expected at least one project"
    # Check ordering: newest first
    if len(projects) > 1:
        assert projects[0].created_at >= projects[1].created_at, "Expected newest first"
    # All should be active
    for p in projects:
        assert p.status == "active", f"Expected active, got {p.status}"

    print(f"  found {len(projects)} active project(s)")
    print("  OK")


async def test_update_project(project_id: int):
    print("=== update_project ===")
    project = await update_project(
        project_id, TEST_USER_ID, name="Updated Name", description="Updated desc"
    )

    assert project is not None
    assert project.name == "Updated Name"
    assert project.description == "Updated desc"
    print(f"  updated: name={project.name}, desc={project.description}")

    # Non-existent
    result = await update_project(99999, TEST_USER_ID, name="x")
    assert result is None, "Expected None for non-existent project"
    print("  non-existent -> None: OK")

    print("  OK")


async def test_archive_project(project_id: int):
    print("=== archive_project ===")
    project = await archive_project(project_id, TEST_USER_ID)

    assert project is not None
    assert project.status == "archived"
    print(f"  archived: id={project.id}, status={project.status}")

    # Should not appear in list
    projects = await list_projects(TEST_USER_ID)
    ids = [p.id for p in projects]
    assert project_id not in ids, "Archived project should not appear in list_projects"
    print("  excluded from list_projects: OK")

    print("  OK")


async def main():
    print("\n--- Project Manager Verification ---\n")

    from src.db import close_db, init_db

    await init_db()

    try:
        project = await test_create_project()
        pid = project.id
        await test_get_project(pid)
        await test_list_projects()
        await test_update_project(pid)
        await test_archive_project(pid)
    finally:
        # Cleanup: remove test uploads directory
        test_uploads = UPLOADS_DIR / str(project.id)
        if test_uploads.exists():
            shutil.rmtree(test_uploads)
            print(f"\n  Cleaned up: {test_uploads}")
        await close_db()

    print("\n[PASS] All project manager tests passed!\n")


if __name__ == "__main__":
    # Windows: psycopg requires SelectorEventLoop
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
