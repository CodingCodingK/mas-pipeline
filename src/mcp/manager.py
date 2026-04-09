"""MCPManager: pipeline-level MCP server connection pool."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.mcp.client import MCPClient
from src.mcp.tool import MCPTool, create_mcp_tools
from src.mcp.transport import HTTPTransport, StdioTransport

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages MCP server connections at pipeline level.

    Multiple agents share the same MCPManager instance.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, list[MCPTool]] = {}  # server_name -> tools

    async def start(self, server_configs: dict[str, Any]) -> None:
        """Connect to all configured MCP servers concurrently.

        Each config is either:
          - {"command": "...", "args": [...], "env": {...}}  (stdio)
          - {"url": "..."}  (HTTP)

        Failed servers are logged and skipped.
        """
        if not server_configs:
            return

        async def _connect_one(name: str, config: dict) -> None:
            try:
                transport = _create_transport(config)
                client = MCPClient(transport)
                await client.initialize()
                tools = await create_mcp_tools(name, client)
                self._clients[name] = client
                self._tools[name] = tools
                logger.info(
                    "MCP server '%s' connected: %d tools",
                    name, len(tools),
                )
            except Exception:
                logger.warning(
                    "MCP server '%s' failed to start, skipping",
                    name, exc_info=True,
                )

        await asyncio.gather(
            *(_connect_one(name, cfg) for name, cfg in server_configs.items()),
        )

    def get_tools(self, server_names: list[str] | None = None) -> list[MCPTool]:
        """Get MCP tools, optionally filtered by server names.

        If server_names is None, returns tools from all connected servers.
        Unknown server names are silently ignored.
        """
        if server_names is None:
            return [t for tools in self._tools.values() for t in tools]

        result: list[MCPTool] = []
        for name in server_names:
            result.extend(self._tools.get(name, []))
        return result

    async def shutdown(self) -> None:
        """Close all server connections. Errors are logged, not raised."""
        for name, client in self._clients.items():
            try:
                await client.shutdown()
                logger.info("MCP server '%s' shut down", name)
            except Exception:
                logger.warning(
                    "Error shutting down MCP server '%s'",
                    name, exc_info=True,
                )
        self._clients.clear()
        self._tools.clear()

    async def __aenter__(self) -> MCPManager:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.shutdown()


def _create_transport(config: dict) -> StdioTransport | HTTPTransport:
    """Create the appropriate transport from a server config dict."""
    if "url" in config:
        return HTTPTransport(url=config["url"])
    if "command" in config:
        return StdioTransport(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
        )
    raise ValueError(f"MCP server config must have 'command' or 'url': {config}")
