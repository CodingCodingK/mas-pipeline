"""Unit test for DB pool config + single-worker startup invariant.

No DB connection required — verifies config plumbing and env-driven checks.
"""

from __future__ import annotations

import logging
import os
import sys

from src.project.config import reload_settings


def _check(name: str, ok: bool) -> None:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        sys.exit(1)


def test_default_pool_size() -> None:
    # Env must not override for this test.
    for var in ("DATABASE_POOL_SIZE", "DATABASE_MAX_OVERFLOW"):
        os.environ.pop(var, None)
    s = reload_settings()
    _check("default pool_size == 20", s.database.pool_size == 20)
    _check("default max_overflow == 40", s.database.max_overflow == 40)
    _check("default pool_pre_ping True", s.database.pool_pre_ping is True)


def test_env_override() -> None:
    os.environ["DATABASE_POOL_SIZE"] = "50"
    os.environ["DATABASE_MAX_OVERFLOW"] = "100"
    try:
        s = reload_settings()
        _check("env pool_size == 50", s.database.pool_size == 50)
        _check("env max_overflow == 100", s.database.max_overflow == 100)
    finally:
        os.environ.pop("DATABASE_POOL_SIZE", None)
        os.environ.pop("DATABASE_MAX_OVERFLOW", None)
        reload_settings()


def test_worker_invariant() -> None:
    from src.main import _check_worker_concurrency

    # Single worker: no raise.
    os.environ["WEB_CONCURRENCY"] = "1"
    try:
        _check_worker_concurrency()
        _check("WEB_CONCURRENCY=1 passes", True)
    except SystemExit:
        _check("WEB_CONCURRENCY=1 passes", False)
    finally:
        os.environ.pop("WEB_CONCURRENCY", None)

    # Reload mode (no env set): no raise.
    try:
        _check_worker_concurrency()
        _check("no worker env passes (reload mode)", True)
    except SystemExit:
        _check("no worker env passes (reload mode)", False)

    # Multi-worker: raises SystemExit.
    os.environ["UVICORN_WORKERS"] = "4"
    try:
        try:
            _check_worker_concurrency()
            _check("UVICORN_WORKERS=4 rejects", False)
        except SystemExit as exc:
            _check("UVICORN_WORKERS=4 rejects (SystemExit)", exc.code == 1)
    finally:
        os.environ.pop("UVICORN_WORKERS", None)

    # WEB_CONCURRENCY=4 also rejects.
    os.environ["WEB_CONCURRENCY"] = "4"
    try:
        try:
            _check_worker_concurrency()
            _check("WEB_CONCURRENCY=4 rejects", False)
        except SystemExit:
            _check("WEB_CONCURRENCY=4 rejects", True)
    finally:
        os.environ.pop("WEB_CONCURRENCY", None)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    test_default_pool_size()
    test_env_override()
    test_worker_invariant()
    print("\nAll db_pool tests passed.")


if __name__ == "__main__":
    main()
