"""Memory tools: MemoryReadTool and MemoryWriteTool for agent access to project memories."""

from __future__ import annotations

from src.tools.base import Tool, ToolContext, ToolResult


class MemoryReadTool(Tool):
    name = "memory_read"
    description = "List or read project memories."
    input_schema: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get"],
                "description": "Action to perform: 'list' all memories or 'get' a specific one.",
            },
            "memory_id": {
                "type": "integer",
                "description": "Memory ID to retrieve (required when action='get').",
            },
        },
        "required": ["action"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return True

    def is_read_only(self, params: dict) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.memory.store import MemoryNotFoundError, get_memory, list_memories

        action = params["action"]
        project_id = context.project_id

        if action == "list":
            if project_id is None:
                return ToolResult(output="Error: no project_id in context", success=False)
            memories = await list_memories(project_id)
            if not memories:
                return ToolResult(output="No memories found for this project.")
            lines = []
            for m in memories:
                lines.append(f"[{m.id}] ({m.type}) {m.name} -- {m.description}")
            return ToolResult(output="\n".join(lines))

        if action == "get":
            memory_id = params.get("memory_id")
            if memory_id is None:
                return ToolResult(output="Error: memory_id is required for action='get'", success=False)
            try:
                mem = await get_memory(int(memory_id))
            except MemoryNotFoundError:
                return ToolResult(output=f"Error: memory not found: {memory_id}", success=False)
            return ToolResult(
                output=f"[{mem.id}] ({mem.type}) {mem.name}\n{mem.description}\n\n{mem.content}"
            )

        return ToolResult(output=f"Error: unknown action '{action}'", success=False)


class MemoryWriteTool(Tool):
    name = "memory_write"
    description = "Create, update, or delete project memories."
    input_schema: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["write", "update", "delete"],
                "description": "Action: 'write' new, 'update' existing, or 'delete'.",
            },
            "type": {
                "type": "string",
                "description": "Memory type: fact, preference, context, instruction.",
            },
            "name": {
                "type": "string",
                "description": "Short name for the memory.",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what the memory contains.",
            },
            "content": {
                "type": "string",
                "description": "Full memory content.",
            },
            "memory_id": {
                "type": "integer",
                "description": "Memory ID (required for update/delete).",
            },
        },
        "required": ["action"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return False

    def is_read_only(self, params: dict) -> bool:
        return False

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.memory.store import (
            MemoryNotFoundError,
            delete_memory,
            update_memory,
            write_memory,
        )

        action = params["action"]
        project_id = context.project_id

        if action == "write":
            if project_id is None:
                return ToolResult(output="Error: no project_id in context", success=False)
            mem_type = params.get("type", "")
            name = params.get("name", "")
            description = params.get("description", "")
            content = params.get("content", "")
            if not all([mem_type, name, description, content]):
                return ToolResult(
                    output="Error: type, name, description, content are all required for write",
                    success=False,
                )
            try:
                mem = await write_memory(
                    project_id=project_id,
                    type=mem_type,
                    name=name,
                    description=description,
                    content=content,
                )
            except ValueError as e:
                return ToolResult(output=f"Error: {e}", success=False)
            return ToolResult(
                output=f"Memory created: id={mem.id}, name='{mem.name}'"
            )

        if action == "update":
            memory_id = params.get("memory_id")
            if memory_id is None:
                return ToolResult(output="Error: memory_id required for update", success=False)
            kwargs = {}
            for field in ("name", "description", "content"):
                if field in params and params[field]:
                    kwargs[field] = params[field]
            if not kwargs:
                return ToolResult(output="Error: at least one of name, description, content required", success=False)
            try:
                await update_memory(int(memory_id), **kwargs)
            except MemoryNotFoundError:
                return ToolResult(output=f"Error: memory not found: {memory_id}", success=False)
            return ToolResult(output=f"Memory updated: id={memory_id}")

        if action == "delete":
            memory_id = params.get("memory_id")
            if memory_id is None:
                return ToolResult(output="Error: memory_id required for delete", success=False)
            try:
                await delete_memory(int(memory_id))
            except MemoryNotFoundError:
                return ToolResult(output=f"Error: memory not found: {memory_id}", success=False)
            return ToolResult(output=f"Memory deleted: id={memory_id}")

        return ToolResult(output=f"Error: unknown action '{action}'", success=False)
