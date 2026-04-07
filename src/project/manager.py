"""Project manager: CRUD operations for projects."""

from __future__ import annotations

from sqlalchemy import func, select, update

from src.db import get_db
from src.models import Project
from src.project.config import ROOT_DIR

UPLOADS_DIR = ROOT_DIR / "uploads"


async def create_project(
    user_id: int,
    name: str,
    pipeline: str,
    description: str | None = None,
    config: dict | None = None,
) -> Project:
    """Create a new project and its uploads directory."""
    project = Project(
        user_id=user_id,
        name=name,
        pipeline=pipeline,
        description=description,
        config=config or {},
    )
    async with get_db() as session:
        session.add(project)
        await session.flush()

        uploads_path = UPLOADS_DIR / str(project.id)
        uploads_path.mkdir(parents=True, exist_ok=True)

    return project


async def get_project(project_id: int, user_id: int) -> Project | None:
    """Get a single project by id, scoped to user."""
    async with get_db() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        return result.scalars().first()


async def list_projects(user_id: int) -> list[Project]:
    """List all active projects for a user, newest first."""
    async with get_db() as session:
        result = await session.execute(
            select(Project)
            .where(Project.user_id == user_id, Project.status == "active")
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())


async def update_project(
    project_id: int, user_id: int, **kwargs: object
) -> Project | None:
    """Update project fields and refresh updated_at. Returns None if not found."""
    async with get_db() as session:
        # Check existence
        result = await session.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        project = result.scalars().first()
        if project is None:
            return None

        # Bulk update with updated_at
        await session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(**kwargs, updated_at=func.now())
        )
        await session.refresh(project)

    return project


async def archive_project(project_id: int, user_id: int) -> Project | None:
    """Soft-delete a project by setting status to 'archived'."""
    return await update_project(project_id, user_id, status="archived")
