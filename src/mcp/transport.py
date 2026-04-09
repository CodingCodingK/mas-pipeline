"""MCP transports: stdio (subprocess) and HTTP."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


class MCPTransport(ABC):
    """Abstract base for MCP JSON-RPC transports."""

    @abstractmethod
    async def start(self) -> None:
        """Establish the connection."""

    @abstractmethod
    async def send(self, message: dict) -> dict | None:
        """Send a JSON-RPC message. Returns response dict for requests, None for notifications."""

    @abstractmethod
    async def close(self) -> None:
        """Tear down the connection."""


class StdioTransport(MCPTransport):
    """Spawn a subprocess, communicate via stdin/stdout line-delimited JSON."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = {**os.environ, **(env or {})}
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )

    async def send(self, message: dict) -> dict | None:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("Transport not started")

        line = json.dumps(message) + "\n"

        async with self._lock:
            self._process.stdin.write(line.encode())
            await self._process.stdin.drain()

            # Notifications (no id) don't expect a response
            if "id" not in message:
                return None

            raw = await self._process.stdout.readline()
            if not raw:
                raise RuntimeError("MCP server closed stdout unexpectedly")
            return json.loads(raw)

    async def close(self) -> None:
        if self._process is not None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (ProcessLookupError, TimeoutError):
                self._process.kill()
            finally:
                self._process = None


class HTTPTransport(MCPTransport):
    """Send JSON-RPC via HTTP POST."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send(self, message: dict) -> dict | None:
        if self._client is None:
            raise RuntimeError("Transport not started")

        # Notifications don't expect a response
        if "id" not in message:
            await self._client.post(self._url, json=message)
            return None

        resp = await self._client.post(self._url, json=message)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
