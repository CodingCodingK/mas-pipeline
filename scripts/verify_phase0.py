"""Phase 0 verification script.

Usage: python -m scripts.verify_phase0
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def verify_config():
    """Verify config loading works."""
    print("=== Config System ===")
    from src.project.config import load_settings

    settings = load_settings()
    print(f"  Models: strong={settings.models.strong}, medium={settings.models.medium}, light={settings.models.light}")
    print(f"  Embedding: {settings.embedding.model} ({settings.embedding.provider})")
    print(f"  DB: {settings.database.postgres_url[:40]}...")
    print(f"  Redis: {settings.database.redis_url}")
    print(f"  Providers: {list(settings.providers.keys())}")
    print("  [OK] Config loaded successfully\n")


async def verify_db():
    """Verify database connections."""
    print("=== Database Connections ===")
    from src.db import close_db, init_db

    try:
        await init_db()
        print("  [OK] PostgreSQL connected")
        print("  [OK] Redis connected")
    except Exception as e:
        print(f"  [FAIL] {e}")
        print("  Hint: Run 'docker compose up -d' first")
    finally:
        await close_db()
    print()


def verify_structure():
    """Verify project directory structure."""
    print("=== Directory Structure ===")
    root = Path(__file__).resolve().parent.parent
    expected_dirs = [
        "src/agent", "src/api", "src/auth", "src/bus", "src/engine",
        "src/export", "src/files", "src/hooks", "src/llm", "src/mcp",
        "src/memory", "src/notify", "src/permissions", "src/project",
        "src/rag", "src/sandbox", "src/session", "src/streaming",
        "src/task", "src/telemetry", "src/tools",
        "agents", "config", "pipelines", "skills", "tests", "web",
    ]
    all_ok = True
    for d in expected_dirs:
        path = root / d
        if path.exists():
            print(f"  [OK] {d}/")
        else:
            print(f"  [MISSING] {d}/")
            all_ok = False
    if all_ok:
        print("  All directories present\n")
    else:
        print("  Some directories missing\n")


def main():
    print("mas-pipeline Phase 0 Verification\n")
    verify_structure()
    verify_config()
    asyncio.run(verify_db())
    print("Done.")


if __name__ == "__main__":
    main()
