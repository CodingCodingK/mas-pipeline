"""Unit tests for src/mcp/jsonrpc.py — make_request, make_notification, parse_response."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp.jsonrpc import JSONRPCError, make_notification, make_request, parse_response

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


print("=== make_request ===")

msg = make_request("tools/list", request_id=1)
check("has jsonrpc", msg["jsonrpc"] == "2.0")
check("has method", msg["method"] == "tools/list")
check("has id", msg["id"] == 1)
check("no params when None", "params" not in msg)

msg2 = make_request("tools/call", params={"name": "test"}, request_id=42)
check("has params", msg2["params"] == {"name": "test"})
check("custom id", msg2["id"] == 42)

print("\n=== make_notification ===")

notif = make_notification("notifications/initialized")
check("has jsonrpc", notif["jsonrpc"] == "2.0")
check("has method", notif["method"] == "notifications/initialized")
check("no id", "id" not in notif)
check("no params when None", "params" not in notif)

notif2 = make_notification("exit", params={"reason": "done"})
check("has params", notif2["params"] == {"reason": "done"})

print("\n=== parse_response: success ===")

result = parse_response({"jsonrpc": "2.0", "result": {"tools": []}, "id": 1})
check("returns result", result == {"tools": []})

result2 = parse_response({"jsonrpc": "2.0", "result": None, "id": 2})
check("returns None result", result2 is None)

print("\n=== parse_response: error ===")

try:
    parse_response({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": 1})
    check("raises JSONRPCError", False)
except JSONRPCError as e:
    check("raises JSONRPCError", True)
    check("error code", e.code == -32600)
    check("error message", "Invalid Request" in e.rpc_message)

try:
    parse_response({"jsonrpc": "2.0", "error": {"code": -1, "message": "fail", "data": {"detail": "x"}}, "id": 1})
    check("error with data raises", False)
except JSONRPCError as e:
    check("error with data raises", True)
    check("error data preserved", e.data == {"detail": "x"})

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
