"""Reshape `document_chunks.embedding` to match `settings.embedding.dimensions`.

Usage:
    python scripts/migrate_embedding_dim.py          # interactive confirmation
    python scripts/migrate_embedding_dim.py --yes    # non-interactive

This is a DESTRUCTIVE operation — existing embeddings are dropped and the
column is recreated at the new dimension. Existing document chunks survive
but must be re-ingested to populate fresh vectors.

Exit codes:
    0  success (or no-op if dims already match)
    1  user aborted
    2  database error
"""

from __future__ import annotations

import argparse
import asyncio
import sys

# psycopg async requires SelectorEventLoop on Windows; the default Proactor loop
# is incompatible. Force the selector policy before any asyncio.run() call.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from src.db import get_db
from src.project.config import get_settings


async def _current_column_dim() -> int | None:
    async with get_db() as session:
        result = await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'document_chunks'::regclass "
                "AND attname = 'embedding'"
            )
        )
        row = result.first()
    if row is None:
        return None
    return int(row[0])


async def _affected_project_ids() -> list[int]:
    async with get_db() as session:
        result = await session.execute(
            text("SELECT DISTINCT project_id FROM documents ORDER BY project_id")
        )
        return [int(r[0]) for r in result.all()]


async def _reshape_column(new_dim: int) -> None:
    async with get_db() as session:
        await session.execute(
            text("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
        )
        await session.execute(
            text(f"ALTER TABLE document_chunks ADD COLUMN embedding vector({new_dim})")
        )
        await session.commit()


async def _main_async(assume_yes: bool) -> int:
    settings = get_settings()
    target_dim = settings.embedding.dimensions
    print(f"Target dimension (settings.embedding.dimensions): {target_dim}")

    try:
        current = await _current_column_dim()
    except Exception as exc:
        print(f"ERROR: could not read current column dim: {exc}", file=sys.stderr)
        return 2

    if current is None:
        print("document_chunks.embedding column not found — nothing to migrate.")
        return 0

    print(f"Current column dimension: {current}")

    if current == target_dim:
        print(f"Already at Vector({target_dim}), nothing to do.")
        return 0

    print()
    print("This will DROP the embedding column and recreate it at the new dimension.")
    print("All existing embeddings will be lost. Chunks will remain but must be re-ingested.")

    if not assume_yes:
        answer = input("Type 'yes' to proceed: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            return 1

    try:
        await _reshape_column(target_dim)
    except Exception as exc:
        print(f"ERROR: reshape failed: {exc}", file=sys.stderr)
        return 2

    print(f"OK — document_chunks.embedding is now Vector({target_dim}).")

    try:
        projects = await _affected_project_ids()
    except Exception:
        projects = []
    if projects:
        print()
        print("Re-ingest required for projects with documents:")
        for pid in projects:
            print(f"  - project_id={pid}")
        print("POST /api/projects/{project_id}/files/{file_id}/ingest for each file.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip interactive confirmation",
    )
    args = parser.parse_args()
    return asyncio.run(_main_async(args.yes))


if __name__ == "__main__":
    sys.exit(main())
