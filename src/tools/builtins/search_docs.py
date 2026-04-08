"""SearchDocsTool: vector similarity search over project documents."""

from __future__ import annotations

from src.tools.base import Tool, ToolContext, ToolResult


class SearchDocsTool(Tool):
    """Search project documents via vector similarity."""

    name = "search_docs"
    description = "Search project documents by semantic similarity. Returns relevant text chunks."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant document chunks",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5)",
            },
        },
        "required": ["query"],
    }

    def is_concurrency_safe(self, params: dict | None = None) -> bool:
        return True

    def is_read_only(self, params: dict | None = None) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        from src.rag.retriever import retrieve

        query = params.get("query", "")
        top_k = params.get("top_k", 5)

        if not query.strip():
            return ToolResult(output="Error: query cannot be empty", success=False)

        if not context.project_id:
            return ToolResult(output="Error: no project context available", success=False)

        results = await retrieve(
            project_id=context.project_id,
            query=query,
            top_k=top_k,
        )

        if not results:
            return ToolResult(output="No relevant documents found.", success=True)

        # Format results
        parts: list[str] = []
        for i, r in enumerate(results, 1):
            source = r.metadata.get("doc_id", "unknown")
            chunk_idx = r.metadata.get("chunk_index", "?")
            parts.append(f"[{i}] (doc:{source}, chunk:{chunk_idx}, score:{r.score:.3f})\n{r.content}")

        return ToolResult(output="\n\n---\n\n".join(parts), success=True)
