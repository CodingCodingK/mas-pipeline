"""MCPTool adapter: wraps MCP server tools as internal Tool interface."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.tools.base import Tool, ToolContext, ToolResult

if TYPE_CHECKING:
    from src.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class MCPTool(Tool):
    """Wraps a single MCP server tool as a Tool instance."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict,
        client: MCPClient,
    ) -> None:
        self.name = f"mcp__{server_name}__{tool_name}"
        self.description = description or f"MCP tool {tool_name} from {server_name}"
        self.input_schema = input_schema or {"type": "object", "properties": {}}
        self._server_name = server_name
        self._original_name = tool_name
        self._client = client

    def is_concurrency_safe(self, params: dict) -> bool:
        return False

    async def call(self, params: dict, context: ToolContext) -> ToolResult:
        try:
            result = await self._client.call_tool(self._original_name, params)
            return ToolResult(output=result, success=True)
        except Exception as exc:
            logger.warning(
                "MCP tool '%s' (server '%s') failed: %s",
                self._original_name, self._server_name, exc,
            )
            return ToolResult(
                output=f"MCP tool error: {exc}",
                success=False,
            )


async def create_mcp_tools(server_name: str, client: MCPClient) -> list[MCPTool]:
    """Discover tools from an MCP server and wrap each as MCPTool."""
    tool_defs = await client.list_tools()
    return [
        MCPTool(
            server_name=server_name,
            tool_name=td["name"],
            description=td.get("description", ""),
            input_schema=td.get("inputSchema", {}),
            client=client,
        )
        for td in tool_defs
    ]
