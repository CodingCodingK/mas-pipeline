"""Built-in tool: web_search — structured web search via Tavily API."""

from __future__ import annotations

import logging

import httpx

from src.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"


def _get_api_key() -> str:
    """Read Tavily API key from settings."""
    from src.project.config import load_settings

    settings = load_settings()
    return settings.tavily.api_key


def _format_results(results: list[dict]) -> str:
    """Format Tavily results into LLM-readable text."""
    if not results:
        return "No results found."

    blocks: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        content = r.get("content", "")
        block = f"[{i}] {title}\n    URL: {url}\n    {content}"
        blocks.append(block)

    return "\n\n".join(blocks)


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for information. Returns structured results with titles, URLs, and content snippets."
    input_schema: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query keywords.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 8).",
                "default": 8,
            },
        },
        "required": ["query"],
    }

    def is_concurrency_safe(self, params: dict) -> bool:
        return True

    def is_read_only(self, params: dict) -> bool:
        return True

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        query: str = params["query"]
        max_results: int = params.get("max_results", 8)

        api_key = _get_api_key()
        if not api_key:
            return ToolResult(
                output="Error: Tavily API key not configured. Set TAVILY_API_KEY environment variable.",
                success=False,
            )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    _TAVILY_URL,
                    json={
                        "api_key": api_key,
                        "query": query,
                        "max_results": max_results,
                        "include_answer": False,
                    },
                )

            if resp.status_code == 401:
                return ToolResult(
                    output="Error: Invalid Tavily API key.",
                    success=False,
                )
            if resp.status_code == 429:
                return ToolResult(
                    output="Error: Tavily API rate limit exceeded.",
                    success=False,
                )
            if resp.status_code != 200:
                return ToolResult(
                    output=f"Error: Tavily API returned status {resp.status_code}: {resp.text[:500]}",
                    success=False,
                )

            data = resp.json()
            results = data.get("results", [])
            output = _format_results(results)

            return ToolResult(
                output=output,
                metadata={"query": query, "result_count": len(results)},
            )

        except httpx.TimeoutException:
            return ToolResult(
                output="Error: Tavily API request timed out.",
                success=False,
            )
        except Exception as exc:
            logger.exception("WebSearchTool error")
            return ToolResult(
                output=f"Error: {exc}",
                success=False,
            )
