"""REST endpoints for two-layer agent file storage (Change 2 / Phase 6.4 step 4)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.api.auth import require_api_key
from src.storage import (
    AgentInUseError,
    InvalidNameError,
    delete_agent_global,
    delete_agent_project,
    list_agents_global,
    merged_agents_view,
    read_agent,
    resolve_agent_file,
    write_agent_global,
    write_agent_project,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


class AgentContent(BaseModel):
    content: str


class AgentItem(BaseModel):
    name: str
    source: str
    description: str = ""
    model_tier: str = ""
    tools: list[str] = []


class AgentListResponse(BaseModel):
    items: list[AgentItem]


class AgentReadResponse(BaseModel):
    name: str
    content: str
    source: str


# ── Global layer ───────────────────────────────────────────


@router.get("/agents", response_model=AgentListResponse)
async def list_global_agents() -> AgentListResponse:
    items = [AgentItem(name=n, source="global") for n in list_agents_global()]
    return AgentListResponse(items=items)


@router.get("/agents/{name}", response_model=AgentReadResponse)
async def read_global_agent(name: str) -> AgentReadResponse:
    try:
        content = read_agent(name, project_id=None)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"agent '{name}' not found")
    return AgentReadResponse(name=name, content=content, source="global")


@router.put("/agents/{name}")
async def put_global_agent(name: str, body: AgentContent) -> Response:
    try:
        created = write_agent_global(name, body.content)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=201 if created else 200)


@router.delete("/agents/{name}", status_code=204)
async def delete_global_agent(name: str) -> Response:
    try:
        delete_agent_global(name)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"agent '{name}' not found")
    except AgentInUseError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "detail": str(e),
                "references": e.references,
            },
        )
    return Response(status_code=204)


# ── Project layer ──────────────────────────────────────────


@router.get(
    "/projects/{project_id}/agents", response_model=AgentListResponse
)
async def list_project_agents(project_id: int) -> AgentListResponse:
    items = [AgentItem(**row) for row in merged_agents_view(project_id)]
    return AgentListResponse(items=items)


@router.get(
    "/projects/{project_id}/agents/{name}", response_model=AgentReadResponse
)
async def read_project_agent(project_id: int, name: str) -> AgentReadResponse:
    try:
        effective_path = resolve_agent_file(name, project_id)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"agent '{name}' not found")
    # Determine source by comparing resolved path's parent to project dir
    content = effective_path.read_text(encoding="utf-8")
    # If the resolved path lives inside projects/<pid>/, it's the project layer
    parts = effective_path.parts
    source = (
        "project"
        if "projects" in parts and str(project_id) in parts
        else "global"
    )
    return AgentReadResponse(name=name, content=content, source=source)


@router.put("/projects/{project_id}/agents/{name}")
async def put_project_agent(
    project_id: int, name: str, body: AgentContent
) -> Response:
    try:
        created = write_agent_project(name, project_id, body.content)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(status_code=201 if created else 200)


@router.delete(
    "/projects/{project_id}/agents/{name}", status_code=204
)
async def delete_project_agent(project_id: int, name: str) -> Response:
    try:
        delete_agent_project(name, project_id)
    except InvalidNameError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"agent '{name}' not found in project {project_id}",
        )
    return Response(status_code=204)


# ── Tools catalogue ───────────────────────────────────────


class ToolItem(BaseModel):
    name: str
    description: str


class ToolListResponse(BaseModel):
    items: list[ToolItem]


@router.get("/tools", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """Return all built-in tools available for agent configuration."""
    from src.tools.builtins import get_all_tools

    tools = get_all_tools()
    items = [
        ToolItem(name=t.name, description=t.description)
        for t in sorted(tools.values(), key=lambda t: t.name)
    ]
    return ToolListResponse(items=items)
