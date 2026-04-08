"""WebSearchTool tests: real API call + error scenario mocks."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.base import ToolContext
from src.tools.builtins.web_search import WebSearchTool, _format_results

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")


ctx = ToolContext(agent_id="test", run_id="r1")
tool = WebSearchTool()

# ── 1. Tool metadata ─────────────────────────────────────

print("\n=== 1. Tool metadata ===")

check("Name is web_search", tool.name == "web_search")
check("Has input_schema", "query" in str(tool.input_schema))
check("Is concurrency safe", tool.is_concurrency_safe({}))
check("Is read only", tool.is_read_only({}))

# ── 2. _format_results ───────────────────────────────────

print("\n=== 2. Result formatting ===")

check("Empty results", _format_results([]) == "No results found.")

sample = [
    {"title": "Title A", "url": "https://a.com", "content": "Content A"},
    {"title": "Title B", "url": "https://b.com", "content": "Content B"},
]
formatted = _format_results(sample)
check("Two results formatted", "[1] Title A" in formatted and "[2] Title B" in formatted)
check("URLs included", "https://a.com" in formatted and "https://b.com" in formatted)
check("Content included", "Content A" in formatted)

# ── 3. Missing API key ───────────────────────────────────

print("\n=== 3. Missing API key ===")


async def test_missing_key():
    with patch("src.tools.builtins.web_search._get_api_key", return_value=""):
        result = await tool.call({"query": "test"}, ctx)
    check("Missing key returns error", not result.success)
    check("Error mentions TAVILY_API_KEY", "TAVILY_API_KEY" in result.output)


asyncio.run(test_missing_key())

# ── 4. API error responses ───────────────────────────────

print("\n=== 4. API error responses ===")


async def test_api_errors():
    # 401
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.tools.builtins.web_search._get_api_key", return_value="fake-key"),
        patch("src.tools.builtins.web_search.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await tool.call({"query": "test"}, ctx)
    check("401 returns error", not result.success)
    check("401 mentions invalid key", "Invalid" in result.output)

    # 429
    mock_resp.status_code = 429
    with (
        patch("src.tools.builtins.web_search._get_api_key", return_value="fake-key"),
        patch("src.tools.builtins.web_search.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await tool.call({"query": "test"}, ctx)
    check("429 returns error", not result.success)
    check("429 mentions rate limit", "rate limit" in result.output.lower())


asyncio.run(test_api_errors())

# ── 5. Successful mock response ──────────────────────────

print("\n=== 5. Successful mock response ===")


async def test_success_mock():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {"title": "RAG Guide", "url": "https://example.com/rag", "content": "RAG is..."},
            {"title": "Vector DB", "url": "https://example.com/vec", "content": "Vectors..."},
        ]
    }
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("src.tools.builtins.web_search._get_api_key", return_value="fake-key"),
        patch("src.tools.builtins.web_search.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await tool.call({"query": "RAG optimization"}, ctx)

    check("Success result", result.success)
    check("Contains RAG Guide", "RAG Guide" in result.output)
    check("Contains Vector DB", "Vector DB" in result.output)
    check("Metadata has query", result.metadata.get("query") == "RAG optimization")
    check("Metadata has count", result.metadata.get("result_count") == 2)


asyncio.run(test_success_mock())

# ── 6. Real API call (if key available) ──────────────────

print("\n=== 6. Real API call ===")

# Load .env for real test
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


async def test_real_api():
    from src.project.config import load_settings
    settings = load_settings()
    if not settings.tavily.api_key:
        print("  [SKIP] TAVILY_API_KEY not set, skipping real API test")
        return

    result = await tool.call({"query": "Python asyncio tutorial", "max_results": 3}, ctx)
    check("Real API returns success", result.success)
    check("Real API has content", len(result.output) > 50)
    check("Real API result count <= 3", result.metadata.get("result_count", 0) <= 3)
    print(f"  [INFO] Got {result.metadata.get('result_count')} results, {len(result.output)} chars")


asyncio.run(test_real_api())

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
