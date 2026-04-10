"""REST endpoints for projects (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.auth import require_api_key
from src.db import get_db
from src.models import Project

router = APIRouter(dependencies=[Depends(require_api_key)])


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    pipeline: str
    status: str


class ProjectList(BaseModel):
    items: list[ProjectOut]


def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        pipeline=p.pipeline,
        status=p.status,
    )


@router.get("/projects", response_model=ProjectList)
async def list_projects() -> ProjectList:
    async with get_db() as db:
        result = await db.execute(select(Project).order_by(Project.id.desc()))
        rows = list(result.scalars().all())
    return ProjectList(items=[_to_out(p) for p in rows])


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int) -> ProjectOut:
    async with get_db() as db:
        project = await db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return _to_out(project)
