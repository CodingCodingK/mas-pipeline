"""Text chunking: split documents into overlapping chunks with metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A text chunk with metadata."""

    content: str
    metadata: dict = field(default_factory=dict)


def chunk_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 100,
    base_metadata: dict | None = None,
) -> list[Chunk]:
    """Split text into overlapping chunks.

    Split priority: section headers (## ) > paragraph breaks (\\n\\n) > hard character cut.
    """
    if not text.strip():
        return []

    base_metadata = base_metadata or {}

    # First split by section headers (## )
    sections = re.split(r"\n(?=## )", text)

    raw_chunks: list[str] = []
    for section in sections:
        if len(section) <= chunk_size:
            raw_chunks.append(section)
        else:
            raw_chunks.extend(_split_by_paragraphs(section, chunk_size))

    # Apply overlap and build final chunks
    chunks: list[Chunk] = []
    for i, raw in enumerate(raw_chunks):
        content = raw.strip()
        if not content:
            continue

        # Add overlap from previous chunk
        if i > 0 and overlap > 0 and raw_chunks[i - 1]:
            prev_text = raw_chunks[i - 1].strip()
            overlap_text = prev_text[-overlap:]
            content = overlap_text + "\n" + content

        chunks.append(Chunk(
            content=content,
            metadata={**base_metadata, "chunk_index": len(chunks)},
        ))

    if not chunks:
        return []

    return chunks


def _split_by_paragraphs(text: str, chunk_size: int) -> list[str]:
    """Split text by paragraph breaks, keeping chunks under chunk_size."""
    paragraphs = text.split("\n\n")
    result: list[str] = []
    current = ""

    for para in paragraphs:
        candidate = (current + "\n\n" + para).strip() if current else para.strip()

        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                result.append(current)
            if len(para) > chunk_size:
                result.extend(_hard_split(para, chunk_size))
                current = ""
            else:
                current = para.strip()

    if current:
        result.append(current)

    return result


def _hard_split(text: str, chunk_size: int) -> list[str]:
    """Hard split text at chunk_size boundaries."""
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
