"""REST endpoints for two-layer pipeline file storage (Change 2 / Phase 6.4 step 4).

Mirrors src/api/agents.py; DELETE never scans for references because
nothing statically references pipelines."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.api.auth import require_api_key
from src.storage import (
    InvalidNameError,
    delete_pipeline_global,
    delete_pipeline_project,
    list_pipelines_global,
    merged_pipelines_view,
    read_pipeline,
    resolve_pipeline_file,
    write_pipeline_global,
    write_pipeline_project,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


class PipelineContent(BaseModel):
    content: str


class PipelineItem(BaseModel):
    name: str
    source: str


class PipelineListResponse(BaseModel):
    items: list[PipelineItem]


class PipelineReadResponse(BaseModel):
    name: str
    content: str
    source: str


# ── Global layer ───────────────────────────────────────────


@router.get("/pipelines", response_model=PipelineListResponse)
async def list_global_pipelines() -> PipelineListResponse:
    items = [
        PipelineItem(name=n, source="global") for n in list_pipelines_global()
    ]
    return PipelineListResponse(items=items)


@router.get("/pipelines/{name}", response_model=PipelineReadResponse)
async def read_global_pipeline(name: str) -> PipelineReadResponse:
    try:
        content = read_pipeline(name, project_id=None)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"pipeline '{name}' not found"
        )
    return PipelineReadResponse(name=name, content=content, source="global")


@router.put("/pipelines/{name}")
async def put_global_pipeline(name: str, body: PipelineContent) -> Response:
    try:
        created = write_pipeline_global(name, body.content)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=201 if created else 200)


@router.delete("/pipelines/{name}", status_code=204)
async def delete_global_pipeline(name: str) -> Response:
    try:
        delete_pipeline_global(name)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"pipeline '{name}' not found"
        )
    return Response(status_code=204)


# ── Project layer ──────────────────────────────────────────


@router.get(
    "/projects/{project_id}/pipelines", response_model=PipelineListResponse
)
async def list_project_pipelines(project_id: int) -> PipelineListResponse:
    items = [PipelineItem(**row) for row in merged_pipelines_view(project_id)]
    return PipelineListResponse(items=items)


@router.get(
    "/projects/{project_id}/pipelines/{name}",
    response_model=PipelineReadResponse,
)
async def read_project_pipeline(
    project_id: int, name: str
) -> PipelineReadResponse:
    try:
        effective_path = resolve_pipeline_file(name, project_id)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"pipeline '{name}' not found"
        )
    content = effective_path.read_text(encoding="utf-8")
    parts = effective_path.parts
    source = (
        "project"
        if "projects" in parts and str(project_id) in parts
        else "global"
    )
    return PipelineReadResponse(name=name, content=content, source=source)


@router.put("/projects/{project_id}/pipelines/{name}")
async def put_project_pipeline(
    project_id: int, name: str, body: PipelineContent
) -> Response:
    try:
        created = write_pipeline_project(name, project_id, body.content)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=201 if created else 200)


@router.delete(
    "/projects/{project_id}/pipelines/{name}", status_code=204
)
async def delete_project_pipeline(project_id: int, name: str) -> Response:
    try:
        delete_pipeline_project(name, project_id)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"pipeline '{name}' not found in project {project_id}",
        )
    return Response(status_code=204)
