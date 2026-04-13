"""RAG pipeline tests: chunking, embedder, retriever, search_docs tool, tool pool."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.chunker import Chunk, chunk_text
from src.rag.parser import ParseResult, parse_markdown, parse_document, SUPPORTED_TYPES
from src.tools.builtins import get_all_tools
from src.tools.builtins.search_docs import SearchDocsTool

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


# ── 1. Chunker ──────────────────────────────────────────

print("\n=== 1. Chunker: basic splitting ===")

# Short text → single chunk
chunks = chunk_text("Hello world", chunk_size=100)
check("short text → 1 chunk", len(chunks) == 1)
check("chunk has content", chunks[0].content == "Hello world")
check("chunk_index=0", chunks[0].metadata.get("chunk_index") == 0)

# Empty text → no chunks
chunks = chunk_text("   ")
check("empty text → 0 chunks", len(chunks) == 0)

chunks = chunk_text("")
check("blank text → 0 chunks", len(chunks) == 0)

print("\n=== 2. Chunker: paragraph splitting ===")

long_text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n\nFourth paragraph."
chunks = chunk_text(long_text, chunk_size=40, overlap=0)
check("multiple chunks", len(chunks) > 1)
check("all have chunk_index", all("chunk_index" in c.metadata for c in chunks))
check("sequential indices", [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks))))

print("\n=== 3. Chunker: section header splitting ===")

section_text = "# Title\nIntro text.\n\n## Section A\nContent A is here.\n\n## Section B\nContent B is here."
chunks = chunk_text(section_text, chunk_size=200, overlap=0)
check("sections split", len(chunks) >= 2)

print("\n=== 4. Chunker: overlap ===")

text_with_paragraphs = "A" * 50 + "\n\n" + "B" * 50 + "\n\n" + "C" * 50
chunks = chunk_text(text_with_paragraphs, chunk_size=60, overlap=20)
check("overlap chunks exist", len(chunks) >= 2)
# Second chunk should start with tail of first chunk's content
if len(chunks) >= 2:
    check("overlap present in chunk 2", len(chunks[1].content) > 50)  # contains overlap

print("\n=== 5. Chunker: base metadata ===")

chunks = chunk_text("Test content", base_metadata={"doc_id": 42, "project_id": 1})
check("base metadata preserved", chunks[0].metadata.get("doc_id") == 42)
check("project_id in metadata", chunks[0].metadata.get("project_id") == 1)
check("chunk_index added", "chunk_index" in chunks[0].metadata)

print("\n=== 6. Chunker: hard split ===")

huge_text = "X" * 2000
chunks = chunk_text(huge_text, chunk_size=500, overlap=0)
check("hard split produces chunks", len(chunks) >= 4)
for c in chunks:
    check(f"chunk <= 600 chars (with overlap margin)", len(c.content) <= 600)

# ── 7. Parser ───────────────────────────────────────────

print("\n=== 7. Parser: markdown ===")

import tempfile, os

with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
    f.write("# Hello\n\nThis is a test document.\n\n## Section\n\nMore content.")
    md_path = f.name

try:
    result = parse_markdown(md_path)
    check("parse_markdown returns ParseResult", isinstance(result, ParseResult))
    check("text has content", "Hello" in result.text)
    check("no images", result.images == [])
finally:
    os.unlink(md_path)

print("\n=== 8. Parser: dispatch ===")

check("supported types", SUPPORTED_TYPES == {"md", "pdf", "docx"})

try:
    parse_document("/fake/path", "csv")
    check("unsupported type raises", False, "no error raised")
except ValueError as e:
    check("unsupported type raises", "csv" in str(e))

print("\n=== 9. Parser: dispatch to markdown ===")

with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
    f.write("Test MD dispatch")
    md_path2 = f.name

try:
    result = parse_document(md_path2, "md")
    check("dispatch md works", result.text == "Test MD dispatch")
finally:
    os.unlink(md_path2)

# ── 10. Embedder (mock) ────────────────────────────────

print("\n=== 10. Embedder: mock ===")

import httpx

from src.rag.embedder import (
    _BATCH_SIZE,
    EmbeddingAPIError,
    EmbeddingAuthError,
    EmbeddingDimensionMismatchError,
    EmbeddingUnreachableError,
    _reset_dim_cache,
    embed,
)

_TEST_DIM = 768


def _make_settings(api_base: str = "http://localhost:11434/v1", api_key: str = "") -> MagicMock:
    s = MagicMock()
    s.embedding.provider = "ollama"
    s.embedding.model = "nomic-embed-text"
    s.embedding.dimensions = _TEST_DIM
    s.embedding.api_base = api_base
    s.embedding.api_key = api_key
    return s


async def _noop_dim_check(configured_dim, api_base):
    return None


async def mock_embed_happy_path():
    """Mock 200 response with correct-length vectors."""
    _reset_dim_cache()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"index": 0, "embedding": [0.1] * _TEST_DIM},
            {"index": 1, "embedding": [0.2] * _TEST_DIM},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch("src.rag.embedder.get_settings", return_value=_make_settings()),
        patch("src.rag.embedder._ensure_db_dim_matches", new=_noop_dim_check),
        patch("src.rag.embedder.httpx.AsyncClient", return_value=mock_client),
    ):
        vectors = await embed(["hello", "world"])
        check("embed returns 2 vectors", len(vectors) == 2)
        check(f"vector dim {_TEST_DIM}", len(vectors[0]) == _TEST_DIM)
        check("vector values", vectors[0][0] == 0.1)

    with patch("src.rag.embedder.get_settings", return_value=_make_settings()):
        vectors = await embed([])
        check("empty input → empty output", vectors == [])


async def mock_embed_unreachable():
    _reset_dim_cache()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

    raised = None
    with (
        patch("src.rag.embedder.get_settings", return_value=_make_settings()),
        patch("src.rag.embedder._ensure_db_dim_matches", new=_noop_dim_check),
        patch("src.rag.embedder.httpx.AsyncClient", return_value=mock_client),
    ):
        try:
            await embed(["hi"])
        except EmbeddingUnreachableError as exc:
            raised = exc

    check("connect error → EmbeddingUnreachableError", isinstance(raised, EmbeddingUnreachableError))
    check("api_base propagated", raised and "11434" in raised.api_base)


async def mock_embed_auth_failure():
    _reset_dim_cache()
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "unauthorized"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    raised = None
    with (
        patch("src.rag.embedder.get_settings", return_value=_make_settings()),
        patch("src.rag.embedder._ensure_db_dim_matches", new=_noop_dim_check),
        patch("src.rag.embedder.httpx.AsyncClient", return_value=mock_client),
    ):
        try:
            await embed(["hi"])
        except EmbeddingAuthError as exc:
            raised = exc

    check("401 → EmbeddingAuthError", isinstance(raised, EmbeddingAuthError))


async def mock_embed_api_error():
    _reset_dim_cache()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "oops"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    raised = None
    with (
        patch("src.rag.embedder.get_settings", return_value=_make_settings()),
        patch("src.rag.embedder._ensure_db_dim_matches", new=_noop_dim_check),
        patch("src.rag.embedder.httpx.AsyncClient", return_value=mock_client),
    ):
        try:
            await embed(["hi"])
        except EmbeddingAPIError as exc:
            raised = exc

    check("500 → EmbeddingAPIError", isinstance(raised, EmbeddingAPIError))
    check("status_code carried", raised and raised.status_code == 500)


async def mock_embed_wrong_dim_from_endpoint():
    _reset_dim_cache()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.1] * 1024}],  # wrong dim
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    raised = None
    with (
        patch("src.rag.embedder.get_settings", return_value=_make_settings()),
        patch("src.rag.embedder._ensure_db_dim_matches", new=_noop_dim_check),
        patch("src.rag.embedder.httpx.AsyncClient", return_value=mock_client),
    ):
        try:
            await embed(["hi"])
        except EmbeddingDimensionMismatchError as exc:
            raised = exc

    check("wrong-dim response → EmbeddingDimensionMismatchError", isinstance(raised, EmbeddingDimensionMismatchError))
    check("observed_dim carried", raised and raised.observed_dim == 1024)
    check("remediation points at script", raised and "migrate_embedding_dim.py" in raised.remediation)


async def mock_embed_no_auth_header_when_key_empty():
    """When api_key is empty (ollama case), Authorization header must be omitted."""
    _reset_dim_cache()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"index": 0, "embedding": [0.1] * _TEST_DIM}],
    }

    captured_headers = {}

    class _CaptureClient:
        def __init__(self, *, base_url, headers, timeout):
            captured_headers.update(headers)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *args, **kwargs):
            return mock_response

    with (
        patch("src.rag.embedder.get_settings", return_value=_make_settings(api_key="")),
        patch("src.rag.embedder._ensure_db_dim_matches", new=_noop_dim_check),
        patch("src.rag.embedder.httpx.AsyncClient", _CaptureClient),
    ):
        await embed(["hi"])

    check("no Authorization header for empty api_key", "Authorization" not in captured_headers)


asyncio.run(mock_embed_happy_path())
asyncio.run(mock_embed_unreachable())
asyncio.run(mock_embed_auth_failure())
asyncio.run(mock_embed_api_error())
asyncio.run(mock_embed_wrong_dim_from_endpoint())
asyncio.run(mock_embed_no_auth_header_when_key_empty())

check("batch size is 100", _BATCH_SIZE == 100)

# ── 11. SearchDocsTool ──────────────────────────────────

print("\n=== 11. SearchDocsTool ===")

tool = SearchDocsTool()
check("tool name", tool.name == "search_docs")
check("concurrency safe", tool.is_concurrency_safe() is True)
check("read only", tool.is_read_only() is True)
check("query required", "query" in tool.input_schema.get("required", []))


async def test_search_docs():
    from src.rag.retriever import RetrievalResult

    mock_results = [
        RetrievalResult(content="Market size is $5B", metadata={"doc_id": 1, "chunk_index": 0}, score=0.92, doc_id=1),
        RetrievalResult(content="Growth rate 15%", metadata={"doc_id": 1, "chunk_index": 1}, score=0.85, doc_id=1),
    ]

    ctx = MagicMock()
    ctx.project_id = 1

    with patch("src.rag.retriever.retrieve", new_callable=AsyncMock, return_value=mock_results):
        result = await tool.call({"query": "market analysis"}, ctx)
        check("search success", result.success is True)
        check("results formatted", "Market size" in result.output)
        check("score in output", "0.920" in result.output)

    # Empty query
    result = await tool.call({"query": ""}, ctx)
    check("empty query fails", result.success is False)

    # No project context
    ctx_no_project = MagicMock()
    ctx_no_project.project_id = None
    result = await tool.call({"query": "test"}, ctx_no_project)
    check("no project fails", result.success is False)

    # No results
    with patch("src.rag.retriever.retrieve", new_callable=AsyncMock, return_value=[]):
        result = await tool.call({"query": "nonexistent"}, ctx)
        check("no results message", "No relevant" in result.output)
        check("no results still success", result.success is True)

    # Embedding unreachable → silent degradation
    from src.rag.embedder import (
        EmbeddingUnreachableError,
        EmbeddingDimensionMismatchError,
    )
    import src.tools.builtins.search_docs as search_docs_mod

    search_docs_mod._logged_error_classes.clear()

    with patch(
        "src.rag.retriever.retrieve",
        new_callable=AsyncMock,
        side_effect=EmbeddingUnreachableError(
            reason="connection refused", api_base="http://localhost:11434/v1"
        ),
    ):
        result = await tool.call({"query": "anything"}, ctx)
        check("unreachable → success=True", result.success is True)
        check("unreachable → RAG-unavailable output", "RAG unavailable" in result.output)

    # Dimension mismatch → still success=True (but ERROR-level log path)
    search_docs_mod._logged_error_classes.clear()
    with patch(
        "src.rag.retriever.retrieve",
        new_callable=AsyncMock,
        side_effect=EmbeddingDimensionMismatchError(
            reason="dim mismatch",
            api_base="http://localhost:11434/v1",
            configured_dim=768,
            observed_dim=1536,
        ),
    ):
        result = await tool.call({"query": "anything"}, ctx)
        check("dim mismatch → success=True", result.success is True)
        check("dim mismatch → RAG-unavailable output", "RAG unavailable" in result.output)


asyncio.run(test_search_docs())

# ── 12. Global tool pool ────────────────────────────────

print("\n=== 12. Global tool pool ===")

all_tools = get_all_tools()
check("search_docs in pool", "search_docs" in all_tools)
check("total tools = 7", len(all_tools) == 7, f"got {len(all_tools)}: {list(all_tools.keys())}")

# ── 13. Retriever (mock) ───────────────────────────────

print("\n=== 13. Retriever: mock ===")

from src.rag.retriever import RetrievalResult

r = RetrievalResult(content="test", metadata={"k": "v"}, score=0.95, doc_id=1)
check("RetrievalResult fields", r.content == "test" and r.score == 0.95 and r.doc_id == 1)
check("RetrievalResult metadata", r.metadata == {"k": "v"})

# ── 13b. File upload must not touch embedder ──────────

print("\n=== 13b. File upload decoupled from embedder ===")

import inspect

from src.files import manager as files_manager

upload_source = inspect.getsource(files_manager)
check(
    "files.manager does not import embedder",
    "rag.embedder" not in upload_source and "from src.rag" not in upload_source,
)
check(
    "files.manager does not call embed()",
    "embed(" not in upload_source,
)


# ── 13c. Ingest EmbeddingError builds structured Job payload ───

print("\n=== 13c. Ingest EmbeddingError → structured Job payload ===")

from src.api.knowledge import _embedding_error_payload, _run_ingest
from src.jobs import Job


async def test_ingest_embedding_error_payload():
    from src.rag.embedder import (
        EmbeddingDimensionMismatchError,
        EmbeddingUnreachableError,
    )

    # Plain unreachable → payload carries error_class / reason / api_base.
    job = Job(kind="ingest")
    async def raise_unreachable(project_id, doc_id, progress_callback=None):
        raise EmbeddingUnreachableError(
            reason="cannot reach http://localhost:11434/v1: refused",
            api_base="http://localhost:11434/v1",
        )

    with patch("src.api.knowledge.ingest_document", side_effect=raise_unreachable):
        await _run_ingest(project_id=1, file_id=1, job=job)

    check("job failed after EmbeddingError", job.status == "failed")
    check("job.error is dict", isinstance(job.error, dict))
    check(
        "payload error_class",
        isinstance(job.error, dict) and job.error.get("error_class") == "EmbeddingUnreachableError",
    )
    check(
        "payload api_base",
        isinstance(job.error, dict) and "11434" in job.error.get("api_base", ""),
    )
    check(
        "payload reason populated",
        isinstance(job.error, dict) and job.error.get("reason", "").startswith("cannot reach"),
    )

    # Dimension mismatch → payload additionally carries configured / observed / remediation
    job2 = Job(kind="ingest")
    async def raise_dim(project_id, doc_id, progress_callback=None):
        raise EmbeddingDimensionMismatchError(
            reason="db column is Vector(1536) but settings.embedding.dimensions=768",
            api_base="http://localhost:11434/v1",
            configured_dim=768,
            observed_dim=1536,
        )

    with patch("src.api.knowledge.ingest_document", side_effect=raise_dim):
        await _run_ingest(project_id=1, file_id=2, job=job2)

    check("dim-mismatch job failed", job2.status == "failed")
    err = job2.error if isinstance(job2.error, dict) else {}
    check("payload error_class dim", err.get("error_class") == "EmbeddingDimensionMismatchError")
    check("payload configured_dim", err.get("configured_dim") == 768)
    check("payload observed_dim", err.get("observed_dim") == 1536)
    check(
        "payload remediation",
        "migrate_embedding_dim.py" in err.get("remediation", ""),
    )

    # Standalone helper produces the same shape
    payload = _embedding_error_payload(
        EmbeddingUnreachableError(reason="x", api_base="y")
    )
    check("helper error_class", payload["error_class"] == "EmbeddingUnreachableError")
    check("helper api_base", payload["api_base"] == "y")


asyncio.run(test_ingest_embedding_error_payload())


# ── 13d. Config loader: ${VAR:default} substitution for embedding ───

print("\n=== 13d. Config loader substitutes embedding env vars ===")

import os as _os

from src.project.config import load_settings


def test_config_env_substitution(tmp_path):
    import tempfile

    yaml_body = """
embedding:
  provider: ollama
  model: nomic-embed-text
  dimensions: 768
  api_base: ${TEST_EMBED_API_BASE:http://localhost:11434/v1}
  api_key: ${TEST_EMBED_API_KEY:}
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(yaml_body)
        tmp = Path(f.name)

    try:
        # Default path (no env vars set)
        _os.environ.pop("TEST_EMBED_API_BASE", None)
        _os.environ.pop("TEST_EMBED_API_KEY", None)
        s = load_settings(global_path=tmp, local_path=Path("/nonexistent"))
        check(
            "default api_base resolves to fallback",
            s.embedding.api_base == "http://localhost:11434/v1",
        )
        check("default api_key resolves to empty", s.embedding.api_key == "")

        # Override via env
        _os.environ["TEST_EMBED_API_BASE"] = "https://api.example.com/v1"
        _os.environ["TEST_EMBED_API_KEY"] = "sk-test-xyz"
        s2 = load_settings(global_path=tmp, local_path=Path("/nonexistent"))
        check(
            "override api_base picks up env",
            s2.embedding.api_base == "https://api.example.com/v1",
        )
        check("override api_key picks up env", s2.embedding.api_key == "sk-test-xyz")
    finally:
        _os.environ.pop("TEST_EMBED_API_BASE", None)
        _os.environ.pop("TEST_EMBED_API_KEY", None)
        tmp.unlink(missing_ok=True)


test_config_env_substitution(None)


# ── 13e. Embedder module import is side-effect-free ───

print("\n=== 13e. Embedder import does not touch network/DB ===")

# Import should not open any HTTP client, contact DB, or read settings that
# would trigger network activity. This is the contract that lets the API
# server start even when the embedding endpoint is unreachable.
import importlib

import src.rag.embedder as _embedder_mod

# Re-import cleanly and verify no exceptions from module top-level code
importlib.reload(_embedder_mod)
check("embedder reload clean", True)
check("EmbeddingError exposed", hasattr(_embedder_mod, "EmbeddingError"))
check(
    "embed is a coroutine function",
    asyncio.iscoroutinefunction(_embedder_mod.embed),
)


# ── 14. DocumentChunk ORM ──────────────────────────────

print("\n=== 14. DocumentChunk ORM ===")

from src.models import DocumentChunk
check("DocumentChunk exists", DocumentChunk.__tablename__ == "document_chunks")
check("has embedding column", hasattr(DocumentChunk, "embedding"))
check("has content column", hasattr(DocumentChunk, "content"))
check("has doc_id column", hasattr(DocumentChunk, "doc_id"))

# ── Summary ──────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
