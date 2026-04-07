"""Built-in tool: read_file — read file contents with optional offset/limit."""

from __future__ import annotations

import os

from src.tools.base import Tool, ToolContext, ToolResult

_MAX_OUTPUT_CHARS = 30_000


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a file. Supports offset and limit "
        "to read specific line ranges. Output includes line numbers."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-based). Optional.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Optional.",
            },
        },
        "required": ["file_path"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        file_path: str = params["file_path"]

        if not os.path.isfile(file_path):
            return ToolResult(
                output=f"Error: file not found: {file_path}",
                success=False,
            )

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as exc:
            return ToolResult(output=f"Error reading file: {exc}", success=False)

        offset = params.get("offset")
        limit = params.get("limit")

        # Convert to 0-based index
        start = (offset - 1) if offset and offset >= 1 else 0
        end = (start + limit) if limit and limit > 0 else len(lines)
        selected = lines[start:end]

        # Format with line numbers
        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i}\t{line.rstrip()}")
        output = "\n".join(numbered)

        # Truncate if needed
        truncated = False
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n[truncated]"
            truncated = True

        return ToolResult(
            output=output,
            success=True,
            metadata={
                "file_size": os.path.getsize(file_path),
                "total_lines": len(lines),
                "truncated": truncated,
            },
        )
