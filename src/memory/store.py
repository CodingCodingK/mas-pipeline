"""Memory CRUD: project-scoped persistent memories backed by PG."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select

from src.db import get_db
from src.models import Memory

logger = logging.getLogger(__name__)

VALID_TYPES = {"fact", "preference", "context", "instruction"}


class MemoryNotFoundError(Exception):
    pass


async def write_memory(
    project_id: int,
    type: str,
    name: str,
    description: str,
    content: str,
    scope: str = "project",
    user_id: int | None = None,
) -> Memory:
    """Create a new memory record."""
    if type not in VALID_TYPES:
        raise ValueError(
            f"Invalid memory type '{type}'. Valid: {', '.join(sorted(VALID_TYPES))}"
        )
    async with get_db() as session:
        mem = Memory(
            project_id=project_id,
            user_id=user_id,
            scope=scope,
            type=type,
            name=name,
            description=description,
            content=content,
        )
        session.add(mem)
        await session.commit()
        await session.refresh(mem)
        return mem


async def update_memory(memory_id: int, **kwargs) -> Memory:
    """Update a memory's fields (name, description, content)."""
    async with get_db() as session:
        mem = await session.get(Memory, memory_id)
        if mem is None:
            raise MemoryNotFoundError(f"Memory not found: {memory_id}")
        for field in ("name", "description", "content"):
            if field in kwargs:
                setattr(mem, field, kwargs[field])
        mem.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(mem)
        return mem


async def delete_memory(memory_id: int) -> None:
    """Hard-delete a memory record."""
    async with get_db() as session:
        mem = await session.get(Memory, memory_id)
        if mem is None:
            raise MemoryNotFoundError(f"Memory not found: {memory_id}")
        await session.delete(mem)
        await session.commit()


async def list_memories(project_id: int) -> list[Memory]:
    """List all memories for a project (lightweight: id, type, name, description)."""
    async with get_db() as session:
        stmt = (
            select(Memory)
            .where(Memory.project_id == project_id)
            .order_by(Memory.id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_memory(memory_id: int) -> Memory:
    """Get a single memory with full content."""
    async with get_db() as session:
        mem = await session.get(Memory, memory_id)
        if mem is None:
            raise MemoryNotFoundError(f"Memory not found: {memory_id}")
        return mem
