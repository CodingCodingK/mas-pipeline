"""Verification for src/rag/ingest progress callback wiring.

Mocks parse_document / chunk_text / embed / get_db to keep this a pure
unit test of the callback ordering — no PG, no embedding API.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.rag.ingest as ingest_mod
from src.rag.parser import ParseResult


# ── Fakes ────────────────────────────────────────────────


@dataclass
class _FakeDoc:
    id: int = 1
    project_id: int = 1
    file_path: str = "/fake/doc.md"
    file_type: str = "md"


@dataclass
class _FakeChunk:
    content: str
    metadata: dict


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value

    def scalars(self):
        return self


class _FakeSession:
    def __init__(self, doc):
        self._doc = doc
        self.executes = []

    async def execute(self, stmt):
        self.executes.append(stmt)
        return _FakeScalarResult(self._doc)

    def add(self, _obj):
        pass


@asynccontextmanager
async def _fake_get_db_factory(doc):
    async def _gen():
        yield _FakeSession(doc)

    @asynccontextmanager
    async def _ctx():
        yield _FakeSession(doc)

    return _ctx


def _make_fake_get_db(doc):
    @asynccontextmanager
    async def _fake_get_db():
        yield _FakeSession(doc)

    return _fake_get_db


# ── Tests ────────────────────────────────────────────────


async def test_callback_emits_full_event_sequence():
    print("=== ingest_document emits full callback sequence ===")

    # Stub parse_document
    def fake_parse(file_path, file_type, images_dir=None):
        return ParseResult(text="hello world " * 100)

    # Stub chunk_text
    def fake_chunk(text, base_metadata=None):
        return [
            _FakeChunk(content=f"chunk_{i}", metadata={"i": i, **(base_metadata or {})})
            for i in range(150)  # > 100 → 2 embedding batches
        ]

    # Stub embed: forward callback to simulate per-batch ticks
    async def fake_embed(texts, *, progress_callback=None):
        # Mimic embedder batching at 100
        total = len(texts)
        out = []
        for i in range(0, total, 100):
            batch = texts[i : i + 100]
            out.extend([[0.0] * 4 for _ in batch])
            if progress_callback is not None:
                await progress_callback(
                    {
                        "event": "embedding_progress",
                        "done": min(i + 100, total),
                        "total": total,
                    }
                )
        return out

    fake_doc = _FakeDoc(id=1, project_id=1)
    ingest_mod.parse_document = fake_parse
    ingest_mod.chunk_text = fake_chunk
    ingest_mod.embed = fake_embed
    ingest_mod.get_db = _make_fake_get_db(fake_doc)

    events = []

    async def cb(ev):
        events.append(ev)

    chunks = await ingest_mod.ingest_document(
        project_id=1, doc_id=1, progress_callback=cb
    )

    assert chunks == 150
    types = [e["event"] for e in events]
    print(f"  events: {types}")

    expected_prefix = ["parsing_started", "parsing_done", "chunking_done"]
    assert types[:3] == expected_prefix, f"Expected prefix {expected_prefix}, got {types[:3]}"

    # Embedding should have 2 ticks (150 → 100, 150)
    embedding_events = [e for e in events if e["event"] == "embedding_progress"]
    assert len(embedding_events) == 2, f"Expected 2 embedding ticks, got {len(embedding_events)}"
    assert embedding_events[0]["done"] == 100
    assert embedding_events[0]["total"] == 150
    assert embedding_events[1]["done"] == 150
    assert embedding_events[1]["total"] == 150

    # Last events: storing → done
    assert types[-2:] == ["storing", "done"], f"Expected ...storing,done; got {types[-2:]}"
    assert events[-1]["chunks"] == 150
    print("  OK")


async def test_callback_emits_failed_on_exception():
    print("=== ingest_document emits failed event on exception, then re-raises ===")

    def fake_parse(file_path, file_type, images_dir=None):
        return ParseResult(text="hello " * 50)

    def fake_chunk(text, base_metadata=None):
        return [_FakeChunk(content="c0", metadata={})]

    async def fake_embed_raises(texts, *, progress_callback=None):
        raise RuntimeError("embedding API timeout")

    fake_doc = _FakeDoc(id=2, project_id=1)
    ingest_mod.parse_document = fake_parse
    ingest_mod.chunk_text = fake_chunk
    ingest_mod.embed = fake_embed_raises
    ingest_mod.get_db = _make_fake_get_db(fake_doc)

    events = []

    async def cb(ev):
        events.append(ev)

    raised = False
    try:
        await ingest_mod.ingest_document(
            project_id=1, doc_id=2, progress_callback=cb
        )
    except RuntimeError as e:
        raised = True
        assert "embedding API timeout" in str(e)

    assert raised, "Expected RuntimeError to propagate"

    types = [e["event"] for e in events]
    print(f"  events: {types}")
    assert types[-1] == "failed", f"Expected last event 'failed', got {types[-1]}"
    assert events[-1]["error"] == "embedding API timeout"
    print("  OK")


async def test_no_callback_is_backward_compatible():
    print("=== ingest_document with no callback works ===")

    def fake_parse(file_path, file_type, images_dir=None):
        return ParseResult(text="hello")

    def fake_chunk(text, base_metadata=None):
        return [_FakeChunk(content="c0", metadata={})]

    async def fake_embed(texts, *, progress_callback=None):
        return [[0.0] * 4 for _ in texts]

    fake_doc = _FakeDoc(id=3, project_id=1)
    ingest_mod.parse_document = fake_parse
    ingest_mod.chunk_text = fake_chunk
    ingest_mod.embed = fake_embed
    ingest_mod.get_db = _make_fake_get_db(fake_doc)

    chunks = await ingest_mod.ingest_document(project_id=1, doc_id=3)
    assert chunks == 1
    print("  OK")


async def main():
    print("\n--- Ingest Progress Callback Verification ---\n")
    await test_callback_emits_full_event_sequence()
    await test_callback_emits_failed_on_exception()
    await test_no_callback_is_backward_compatible()
    print("\n[PASS] All ingest progress tests passed!\n")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
