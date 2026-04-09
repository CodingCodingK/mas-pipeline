"""MCP client: protocol lifecycle — initialize, tool discovery, tool invocation, shutdown."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.mcp.jsonrpc import JSONRPCError, make_notification, make_request, parse_response

if TYPE_CHECKING:
    from src.mcp.transport import MCPTransport

logger = logging.getLogger(__name__)

# MCP protocol version we support
_PROTOCOL_VERSION = "2024-11-05"

# Incrementing request ID counter per client
_REQUEST_ID_START = 1


class MCPClient:
    """Client for a single MCP server connection."""

    def __init__(self, transport: MCPTransport) -> None:
        self._transport = transport
        self._next_id = _REQUEST_ID_START
        self._server_capabilities: dict = {}

    def _make_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    async def initialize(self) -> dict:
        """Perform MCP initialize handshake.

        1. Send initialize request with protocol version and client capabilities.
        2. Receive server capabilities.
        3. Send initialized notification.
        """
        await self._transport.start()

        resp = await self._transport.send(make_request(
            "initialize",
            params={
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mas-pipeline", "version": "0.1.0"},
            },
            request_id=self._make_id(),
        ))

        result = parse_response(resp)
        self._server_capabilities = result.get("capabilities", {})

        # Send initialized notification (no response expected)
        await self._transport.send(make_notification("notifications/initialized"))

        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover tools from the MCP server.

        Returns list of dicts with keys: name, description, inputSchema.
        """
        resp = await self._transport.send(make_request(
            "tools/list",
            request_id=self._make_id(),
        ))

        result = parse_response(resp)
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """Invoke a tool on the MCP server.

        Returns the result content as a string.
        Raises JSONRPCError if the server returns isError=true.
        """
        resp = await self._transport.send(make_request(
            "tools/call",
            params={"name": name, "arguments": arguments or {}},
            request_id=self._make_id(),
        ))

        result = parse_response(resp)

        # MCP tools/call returns {content: [{type, text}], isError?}
        if result.get("isError"):
            content = _extract_content_text(result)
            raise JSONRPCError(code=-1, message=content or "Tool execution failed")

        return _extract_content_text(result) or ""

    async def shutdown(self) -> None:
        """Graceful shutdown: send shutdown request, exit notification, close transport."""
        try:
            resp = await self._transport.send(make_request(
                "shutdown",
                request_id=self._make_id(),
            ))
            if resp:
                parse_response(resp)  # Check for errors

            await self._transport.send(make_notification("exit"))
        except Exception:
            logger.debug("Error during MCP shutdown, closing transport anyway", exc_info=True)
        finally:
            await self._transport.close()


def _extract_content_text(result: dict) -> str | None:
    """Extract text from MCP content blocks [{type: "text", text: "..."}]."""
    content = result.get("content", [])
    texts = [block.get("text", "") for block in content if block.get("type") == "text"]
    return "\n".join(texts) if texts else None
