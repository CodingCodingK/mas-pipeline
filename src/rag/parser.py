"""Document parsing: MD, PDF, DOCX → text + images."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"md", "pdf", "docx"}


@dataclass
class ParseResult:
    """Result of parsing a document."""

    text: str
    images: list[dict] = field(default_factory=list)  # [{page, path} or {name, path}]


def parse_markdown(file_path: str | Path) -> ParseResult:
    """Parse a Markdown file — just read the text."""
    text = Path(file_path).read_text(encoding="utf-8")
    return ParseResult(text=text)


def parse_pdf(file_path: str | Path, images_dir: str | Path | None = None) -> ParseResult:
    """Parse a PDF using pymupdf4llm for Markdown extraction + page image rendering."""
    import pymupdf  # noqa: F811
    import pymupdf4llm

    file_path = Path(file_path)
    text = pymupdf4llm.to_markdown(str(file_path))

    images: list[dict] = []
    if images_dir is not None:
        images_dir = Path(images_dir)
        images_dir.mkdir(parents=True, exist_ok=True)

        doc = pymupdf.open(str(file_path))
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Check if page has images
            if page.get_images():
                pix = page.get_pixmap(dpi=150)
                img_path = images_dir / f"page_{page_num + 1}.png"
                pix.save(str(img_path))
                images.append({"page": page_num + 1, "path": str(img_path)})
        doc.close()

    return ParseResult(text=text, images=images)


def parse_docx(file_path: str | Path, images_dir: str | Path | None = None) -> ParseResult:
    """Parse a DOCX file using python-docx."""
    from docx import Document as DocxDocument

    file_path = Path(file_path)
    doc = DocxDocument(str(file_path))

    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n\n".join(paragraphs)

    images: list[dict] = []
    if images_dir is not None:
        images_dir = Path(images_dir)
        images_dir.mkdir(parents=True, exist_ok=True)

        for i, rel in enumerate(doc.part.rels.values()):
            if "image" in rel.reltype:
                img_data = rel.target_part.blob
                ext = Path(rel.target_ref).suffix or ".png"
                img_name = f"image_{i}{ext}"
                img_path = images_dir / img_name
                img_path.write_bytes(img_data)
                images.append({"name": img_name, "path": str(img_path)})

    return ParseResult(text=text, images=images)


def parse_document(
    file_path: str | Path,
    file_type: str,
    images_dir: str | Path | None = None,
) -> ParseResult:
    """Dispatch to the correct parser based on file type."""
    file_type = file_type.lower().lstrip(".")

    if file_type not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported file type: '{file_type}'. Supported: {SUPPORTED_TYPES}")

    if file_type == "md":
        return parse_markdown(file_path)
    if file_type == "pdf":
        return parse_pdf(file_path, images_dir)
    if file_type == "docx":
        return parse_docx(file_path, images_dir)

    raise ValueError(f"Unsupported file type: '{file_type}'")
