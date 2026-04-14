"""Regression guard for spec `export-business`: the exporter must not cache
a run's final_output. If a reject→rerun→approve cycle overwrites the run's
metadata.final_output in PG, the next export_markdown() call must serve the
second value, not the first.

This is a unit-level regression, not an end-to-end pipeline test. We mock
`src.export.exporter.get_run` to return evolving run states across calls
and assert the exporter always reads the latest value.

Run: python scripts/test_exporter_freshness.py
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.export.exporter as exporter_mod
from src.export.exporter import (
    NoFinalOutputError,
    RunNotFinishedError,
    RunNotFoundError,
    export_markdown,
)


@dataclass
class _FakeRun:
    run_id: str = "run-abcd1234"
    pipeline: str = "blog_with_review"
    status: str = "completed"
    metadata_: dict[str, Any] = field(default_factory=dict)


def _install_get_run(runs_by_call: list[_FakeRun | None]) -> list[int]:
    """Replace exporter_mod.get_run with an async stub that returns the
    next item from `runs_by_call` on each call. Returns a 1-element list
    used as a mutable call counter.
    """
    counter = [0]

    async def _fake_get_run(run_id: str) -> _FakeRun | None:
        idx = counter[0]
        counter[0] += 1
        return runs_by_call[idx]

    exporter_mod.get_run = _fake_get_run  # type: ignore[assignment]
    return counter


def test_exporter_serves_latest_final_output() -> None:
    """reject→rerun→approve cycle: second call must see the updated value."""
    first = _FakeRun(metadata_={"final_output": "FIRST DRAFT"})
    second = _FakeRun(metadata_={"final_output": "SECOND DRAFT (after reject)"})
    _install_get_run([first, second])

    a = asyncio.run(export_markdown("run-abcd1234"))
    assert a.content == "FIRST DRAFT", a.content

    b = asyncio.run(export_markdown("run-abcd1234"))
    assert b.content == "SECOND DRAFT (after reject)", b.content


def test_exporter_filename_sanitizes_pipeline_name() -> None:
    run = _FakeRun(
        pipeline="blog with review/中文",
        metadata_={"final_output": "hello"},
    )
    _install_get_run([run])
    a = asyncio.run(export_markdown("run-abcd1234"))
    assert a.filename.startswith("blog_with_review_"), a.filename
    assert a.filename.endswith(".md"), a.filename
    # Display filename keeps the non-ASCII form
    assert "中文" in a.display_filename, a.display_filename


def test_exporter_raises_for_missing_run() -> None:
    _install_get_run([None])
    try:
        asyncio.run(export_markdown("nope"))
    except RunNotFoundError:
        return
    raise AssertionError("expected RunNotFoundError")


def test_exporter_raises_for_unfinished_run() -> None:
    run = _FakeRun(status="running", metadata_={"final_output": "partial"})
    _install_get_run([run])
    try:
        asyncio.run(export_markdown("run-abcd1234"))
    except RunNotFinishedError:
        return
    raise AssertionError("expected RunNotFinishedError")


def test_exporter_raises_when_final_output_empty() -> None:
    run = _FakeRun(metadata_={"final_output": ""})
    _install_get_run([run])
    try:
        asyncio.run(export_markdown("run-abcd1234"))
    except NoFinalOutputError:
        return
    raise AssertionError("expected NoFinalOutputError")


def main() -> None:
    tests = [
        test_exporter_serves_latest_final_output,
        test_exporter_filename_sanitizes_pipeline_name,
        test_exporter_raises_for_missing_run,
        test_exporter_raises_for_unfinished_run,
        test_exporter_raises_when_final_output_empty,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
