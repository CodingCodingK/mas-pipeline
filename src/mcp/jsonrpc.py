"""JSON-RPC 2.0 message builders and response parser."""

from __future__ import annotations

from typing import Any


class JSONRPCError(Exception):
    """Raised when a JSON-RPC response contains an error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.rpc_message = message
        self.data = data
        super().__init__(f"JSON-RPC error {code}: {message}")


def make_request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request message."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        msg["params"] = params
    return msg


def make_notification(method: str, params: dict | None = None) -> dict:
    """Build a JSON-RPC 2.0 notification (no id, no response expected)."""
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def parse_response(data: dict) -> Any:
    """Parse a JSON-RPC 2.0 response. Returns result or raises JSONRPCError."""
    if "error" in data:
        err = data["error"]
        raise JSONRPCError(
            code=err.get("code", -1),
            message=err.get("message", "Unknown error"),
            data=err.get("data"),
        )
    return data.get("result")
