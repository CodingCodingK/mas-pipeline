"""Unit tests for src/mcp/transport.py — StdioTransport, HTTPTransport."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp.transport import HTTPTransport, StdioTransport

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


# --- StdioTransport ---

print("=== StdioTransport: start/send/close ===")


async def test_stdio():
    transport = StdioTransport(command="echo", args=["hello"])

    # Mock subprocess
    mock_proc = MagicMock()
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = AsyncMock()
    mock_proc.stdin.close = MagicMock()
    mock_proc.stdout = MagicMock()
    response_data = {"jsonrpc": "2.0", "result": {"ok": True}, "id": 1}
    mock_proc.stdout.readline = AsyncMock(return_value=(json.dumps(response_data) + "\n").encode())
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
        await transport.start()
        check("start creates process", transport._process is not None)

        # Send request (has id)
        resp = await transport.send({"jsonrpc": "2.0", "method": "test", "id": 1})
        check("send returns response", resp == response_data)
        check("stdin written", mock_proc.stdin.write.called)

        # Send notification (no id)
        resp2 = await transport.send({"jsonrpc": "2.0", "method": "notify"})
        check("notification returns None", resp2 is None)

        # Close
        await transport.close()
        check("close terminates process", mock_proc.terminate.called)
        check("process cleared", transport._process is None)


asyncio.run(test_stdio())

print("\n=== StdioTransport: env merge ===")

transport = StdioTransport(command="test", env={"MY_VAR": "hello"})
check("env merged with os.environ", "MY_VAR" in transport._env)
check("env value correct", transport._env["MY_VAR"] == "hello")
check("PATH preserved", "PATH" in transport._env or "Path" in transport._env)

# --- HTTPTransport ---

print("\n=== HTTPTransport: start/send/close ===")


async def test_http():
    transport = HTTPTransport(url="http://localhost:3001/mcp")

    await transport.start()
    check("start creates client", transport._client is not None)

    # Mock the client
    mock_response = MagicMock()
    mock_response.json.return_value = {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}
    mock_response.raise_for_status = MagicMock()
    transport._client.post = AsyncMock(return_value=mock_response)

    # Send request
    resp = await transport.send({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    check("http returns response", resp == {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1})

    # Send notification
    resp2 = await transport.send({"jsonrpc": "2.0", "method": "notify"})
    check("notification returns None", resp2 is None)

    # Close
    transport._client.aclose = AsyncMock()
    await transport.close()
    check("close clears client", transport._client is None)


asyncio.run(test_http())

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
