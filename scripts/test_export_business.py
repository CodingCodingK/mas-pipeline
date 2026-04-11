"""Verification for Change 1.6 — export business layer.

No PG: monkey-patches src.export.exporter.get_run to return fake WorkflowRun
instances, so this runs standalone without touching the database.

Run: python scripts/test_export_business.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import platform
import sys
from pathlib import Path
from types import SimpleNamespace

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.export import (
    ExportArtifact,
    ExportError,
    NoFinalOutputError,
    RunNotFinishedError,
    RunNotFoundError,
    export_markdown,
)
from src.export import exporter as exporter_mod

passed = 0
failed = 0


def _ok(label: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {label}")


def _fail(label: str, detail: str) -> None:
    global failed
    failed += 1
    print(f"  FAIL  {label}: {detail}")


def _fake_run(
    *,
    run_id: str = "abcdef1234567890",
    pipeline: str | None = "blog_generation",
    status: str = "completed",
    metadata_: dict | None = None,
):
    return SimpleNamespace(
        run_id=run_id,
        pipeline=pipeline,
        status=status,
        metadata_=metadata_ if metadata_ is not None else {},
    )


def _patch_get_run(result):
    async def _fn(_run_id):
        return result
    exporter_mod.get_run = _fn


async def section_happy_path():
    print("\n[section] happy path")
    _patch_get_run(_fake_run(metadata_={"final_output": "# Report\n\nhello"}))
    artifact = await export_markdown("abcdef1234567890")

    if isinstance(artifact, ExportArtifact):
        _ok("returns ExportArtifact")
    else:
        _fail("returns ExportArtifact", f"got {type(artifact)}")

    if artifact.content == "# Report\n\nhello":
        _ok("content is raw final_output")
    else:
        _fail("content is raw final_output", repr(artifact.content))

    if artifact.content_type == "text/markdown; charset=utf-8":
        _ok("content_type")
    else:
        _fail("content_type", artifact.content_type)

    if artifact.filename == "blog_generation_abcdef12.md":
        _ok("filename is {pipeline}_{run_id[:8]}.md")
    else:
        _fail("filename", artifact.filename)

    if artifact.display_filename == "blog_generation_abcdef12.md":
        _ok("display_filename matches when pipeline is ASCII")
    else:
        _fail("display_filename ASCII", artifact.display_filename)

    # non-ASCII pipeline: display_filename keeps original, filename sanitizes
    _patch_get_run(_fake_run(
        pipeline="博客生成",
        run_id="abcdef1234567890",
        metadata_={"final_output": "x"},
    ))
    a = await export_markdown("rid")
    if a.display_filename == "博客生成_abcdef12.md":
        _ok("display_filename preserves non-ASCII")
    else:
        _fail("display_filename non-ASCII", a.display_filename)
    if a.filename == "_____abcdef12.md":
        _ok("filename sanitizes non-ASCII in parallel")
    else:
        _fail("filename non-ASCII", a.filename)

    try:
        artifact.content = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        _ok("ExportArtifact is frozen")
    except Exception as e:
        _fail("ExportArtifact is frozen", f"wrong exception: {e!r}")
    else:
        _fail("ExportArtifact is frozen", "assignment succeeded")


async def section_not_found():
    print("\n[section] RunNotFoundError")
    _patch_get_run(None)
    try:
        await export_markdown("missing")
    except RunNotFoundError:
        _ok("raises RunNotFoundError when get_run returns None")
    except Exception as e:
        _fail("RunNotFoundError", f"got {type(e).__name__}")
    else:
        _fail("RunNotFoundError", "no exception")

    # Inherits ExportError
    if issubclass(RunNotFoundError, ExportError):
        _ok("RunNotFoundError subclasses ExportError")
    else:
        _fail("RunNotFoundError subclass", "no")


async def section_not_finished():
    print("\n[section] RunNotFinishedError")
    for st in ("pending", "running", "paused", "failed", "cancelled"):
        _patch_get_run(_fake_run(status=st, metadata_={"final_output": ""}))
        try:
            await export_markdown("rid")
        except RunNotFinishedError as e:
            if st in str(e):
                _ok(f"status={st!r} raises with status in message")
            else:
                _fail(f"status={st!r}", f"message missing status: {e}")
        except Exception as e:
            _fail(f"status={st!r}", f"wrong exception: {type(e).__name__}")
        else:
            _fail(f"status={st!r}", "no exception")

    # status check runs before final_output check
    _patch_get_run(_fake_run(status="failed", metadata_={"final_output": ""}))
    try:
        await export_markdown("rid")
    except RunNotFinishedError:
        _ok("failed+empty_output raises RunNotFinishedError (not NoFinalOutputError)")
    except NoFinalOutputError:
        _fail("precedence", "got NoFinalOutputError — status check should run first")

    if issubclass(RunNotFinishedError, ExportError):
        _ok("RunNotFinishedError subclasses ExportError")
    else:
        _fail("RunNotFinishedError subclass", "no")


async def section_no_output():
    print("\n[section] NoFinalOutputError")
    cases = [
        ("missing key", {}),
        ("None value", {"final_output": None}),
        ("empty string", {"final_output": ""}),
    ]
    for label, md in cases:
        _patch_get_run(_fake_run(status="completed", metadata_=md))
        try:
            await export_markdown("rid")
        except NoFinalOutputError:
            _ok(f"completed + {label} raises NoFinalOutputError")
        except Exception as e:
            _fail(label, f"wrong exception: {type(e).__name__}")
        else:
            _fail(label, "no exception")

    # metadata_ is None (not just empty dict)
    _patch_get_run(_fake_run(status="completed", metadata_=None))
    try:
        await export_markdown("rid")
    except NoFinalOutputError:
        _ok("completed + metadata_=None raises NoFinalOutputError")
    except Exception as e:
        _fail("metadata_=None", f"wrong exception: {type(e).__name__}")

    if issubclass(NoFinalOutputError, ExportError):
        _ok("NoFinalOutputError subclasses ExportError")
    else:
        _fail("NoFinalOutputError subclass", "no")


async def section_filename():
    print("\n[section] filename derivation")

    # special chars in pipeline name
    _patch_get_run(_fake_run(
        pipeline="blog/test",
        run_id="abcdef1234567890",
        metadata_={"final_output": "x"},
    ))
    a = await export_markdown("rid")
    if a.filename == "blog_test_abcdef12.md":
        _ok("'blog/test' -> 'blog_test_abcdef12.md'")
    else:
        _fail("blog/test", a.filename)

    # None pipeline
    _patch_get_run(_fake_run(
        pipeline=None,
        run_id="abcdef1234567890",
        metadata_={"final_output": "x"},
    ))
    a = await export_markdown("rid")
    if a.filename == "run_abcdef12.md":
        _ok("pipeline=None -> 'run_abcdef12.md'")
    else:
        _fail("None pipeline", a.filename)

    # non-ASCII
    _patch_get_run(_fake_run(
        pipeline="博客_test",
        run_id="deadbeefcafebabe",
        metadata_={"final_output": "x"},
    ))
    a = await export_markdown("rid")
    # 博 and 客 each become '_'; _test stays; so '__test'? actually: 博客 -> __, then _test stays -> '___test'
    # "博客_test" -> "___test" (博->_, 客->_, _->_, t, e, s, t)
    if a.filename == "___test_deadbeef.md":
        _ok("non-ASCII collapsed to underscores")
    else:
        _fail("non-ASCII", a.filename)

    # run_id shorter than 8 chars — edge case defensiveness
    _patch_get_run(_fake_run(
        pipeline="p",
        run_id="abc",
        metadata_={"final_output": "x"},
    ))
    a = await export_markdown("rid")
    if a.filename == "p_abc.md":
        _ok("short run_id not padded")
    else:
        _fail("short run_id", a.filename)


async def section_catch_base():
    print("\n[section] base-class catch")
    _patch_get_run(None)
    caught = None
    try:
        await export_markdown("missing")
    except ExportError as e:
        caught = type(e).__name__
    if caught == "RunNotFoundError":
        _ok("single except ExportError catches RunNotFoundError")
    else:
        _fail("base catch", f"caught={caught}")


async def main():
    original_get_run = exporter_mod.get_run
    try:
        await section_happy_path()
        await section_not_found()
        await section_not_finished()
        await section_no_output()
        await section_filename()
        await section_catch_base()
    finally:
        exporter_mod.get_run = original_get_run

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
