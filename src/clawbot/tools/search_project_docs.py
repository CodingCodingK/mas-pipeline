"""search_project_docs — vector search with explicit project_id param.

Unlike src.tools.builtins.search_docs (which reads context.project_id),
clawbot never has a pinned project_id on its tool_context. Project is a
parameter the LLM selects per-call based on conversation history.
"""

from __future__ import annotations

import logging

from src.rag.embedder import EmbeddingError
from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class SearchProjectDocsTool(Tool):
    name = "search_project_docs"
    description = (
        "Semantic search over a specific project's documents. "
        "project_id is an explicit parameter — not read from session state."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "integer",
                "description": "Numeric project id to search within.",
            },
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "top_k": {
                "type": "integer",
                "description": "Max results to return (default 5).",
            },
        },
        "required": ["project_id", "query"],
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    def is_read_only(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.rag.retriever import retrieve

        try:
            project_id = int(params["project_id"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(output="Error: project_id must be an integer", success=False)

        query = (params.get("query") or "").strip()
        if not query:
            return ToolResult(output="Error: query cannot be empty", success=False)
        top_k = int(params.get("top_k") or 5)

        try:
            results = await retrieve(project_id=project_id, query=query, top_k=top_k)
        except EmbeddingError as exc:
            logger.warning("search_project_docs: %s", exc)
            return ToolResult(output="RAG unavailable: no results", success=True)

        if not results:
            return ToolResult(output="No relevant documents found.", success=True)

        parts: list[str] = []
        for i, r in enumerate(results, 1):
            source = r.metadata.get("doc_id", "unknown")
            chunk_idx = r.metadata.get("chunk_index", "?")
            parts.append(
                f"[{i}] (doc:{source}, chunk:{chunk_idx}, score:{r.score:.3f})\n{r.content}"
            )
        return ToolResult(output="\n\n---\n\n".join(parts), success=True)
