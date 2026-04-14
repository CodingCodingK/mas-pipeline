"""Built-in tool: write_file — write text content to a file path."""

from __future__ import annotations

import os

from src.tools.base import Tool, ToolContext, ToolResult


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write text content to a file. Creates parent directories if missing. "
        "Overwrites by default; pass append=true to append instead. "
        "file_path is normalized via realpath before the permission layer checks it, "
        "so relative traversal (../) is resolved against its real target."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the target file.",
            },
            "content": {
                "type": "string",
                "description": "Text content to write.",
            },
            "append": {
                "type": "boolean",
                "description": "When true, append to existing file instead of overwriting. Defaults to false.",
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding. Defaults to utf-8.",
            },
        },
        "required": ["file_path", "content"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return False

    def normalize_params(self, params: dict) -> dict:
        """Resolve file_path via realpath before permission check.

        The PreToolUse permission hook pattern-matches against params[file_path]
        using fnmatch. Rules are written in project-relative form like
        ``write_file(src/**)``, so after realpath we re-relativize the result
        against cwd (when still inside cwd). Paths outside cwd stay absolute.

        Forward-slash normalization is applied so Windows backslashes do not
        break pattern matching.
        """
        fp = params.get("file_path")
        if not isinstance(fp, str) or not fp:
            return params

        abs_path = os.path.realpath(fp)
        cwd = os.path.realpath(os.getcwd())
        try:
            rel = os.path.relpath(abs_path, cwd)
        except ValueError:
            rel = abs_path  # different drive letter on Windows
        # If relpath escapes cwd (starts with ..), keep the absolute form
        # so rules cannot be bypassed by chdir() tricks.
        if rel.startswith(".."):
            normalized = abs_path
        else:
            normalized = rel

        params = dict(params)
        params["file_path"] = normalized.replace("\\", "/")
        return params

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        # file_path is already realpath+cwd-normalized by normalize_params()
        file_path: str = params["file_path"]
        content: str = params["content"]
        # If it came through the orchestrator with normalize_params, it is a
        # cwd-relative path (or absolute for outside-cwd). open() handles both.
        append: bool = bool(params.get("append", False))
        encoding: str = params.get("encoding") or "utf-8"

        try:
            parent = os.path.dirname(file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            mode = "a" if append else "w"
            with open(file_path, mode, encoding=encoding) as f:
                n = f.write(content)
            # Report byte length of encoded content for determinism
            bytes_written = len(content.encode(encoding, errors="replace"))
            return ToolResult(
                output=f"Wrote {bytes_written} bytes to {file_path}",
                success=True,
                metadata={
                    "file_path": file_path,
                    "bytes": bytes_written,
                    "chars": n,
                    "append": append,
                },
            )
        except OSError as exc:
            return ToolResult(
                output=f"Error writing file: {exc}",
                success=False,
            )
        except UnicodeEncodeError as exc:
            return ToolResult(
                output=f"Error encoding content ({encoding}): {exc}",
                success=False,
            )
