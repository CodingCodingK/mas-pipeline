"""API Key authentication for /api/* routers.

Phase 6.1: a single header (`X-API-Key`) checked against `settings.api_keys`.
An empty `api_keys` list disables auth (development mode).
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from src.project.config import get_settings


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: validate `X-API-Key` against `settings.api_keys`.

    - Empty `settings.api_keys` → all requests pass (dev mode).
    - Otherwise the header must match one of the configured keys.
    - Failure raises HTTP 401 with `{"detail": "invalid api key"}`.
    """
    valid_keys = get_settings().api_keys
    if not valid_keys:
        return  # dev mode: auth disabled
    if x_api_key is None or x_api_key not in valid_keys:
        raise HTTPException(status_code=401, detail="invalid api key")
