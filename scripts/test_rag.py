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

from src.rag.embedder import embed, _BATCH_SIZE

mock_settings = MagicMock()
mock_settings.embedding.provider = "openai"
mock_settings.embedding.model = "text-embedding-3-small"
mock_settings.providers = {"openai": MagicMock(api_base="https://api.openai.com/v1", api_key="test")}


async def mock_embed_call():
    """Test embed with mocked HTTP."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"index": 0, "embedding": [0.1] * 1536},
            {"index": 1, "embedding": [0.2] * 1536},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("src.rag.embedder.get_settings", return_value=mock_settings), \
         patch("src.rag.embedder.httpx.AsyncClient", return_value=mock_client):
        vectors = await embed(["hello", "world"])
        check("embed returns 2 vectors", len(vectors) == 2)
        check("vector dim 1536", len(vectors[0]) == 1536)
        check("vector values", vectors[0][0] == 0.1)

    # Empty input
    with patch("src.rag.embedder.get_settings", return_value=mock_settings):
        vectors = await embed([])
        check("empty input → empty output", vectors == [])


asyncio.run(mock_embed_call())

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
