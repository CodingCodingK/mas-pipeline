"""Verification for Change 2 — layered file storage resolver + scanner.

No PG, no HTTP: exercises src/storage/layered.py against a fresh tmpdir root.
Monkey-patches `src.storage.layered._ROOT` for each top-level section.

Run: python scripts/test_layered_storage.py
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import sys
import tempfile
from pathlib import Path

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage import (
    AgentInUseError,
    InvalidNameError,
    delete_agent_global,
    delete_agent_project,
    delete_pipeline_global,
    delete_pipeline_project,
    find_agent_references_global,
    list_agents_global,
    list_agents_project,
    list_pipelines_global,
    list_pipelines_project,
    merged_agents_view,
    merged_pipelines_view,
    read_agent,
    read_pipeline,
    resolve_agent_file,
    resolve_pipeline_file,
    write_agent_global,
    write_agent_project,
    write_pipeline_global,
    write_pipeline_project,
)
from src.storage import layered as layered_mod

passed = 0
failed = 0


def section(name: str) -> None:
    print(f"\n=== {name} ===")


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def fresh_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="layered_test_"))
    layered_mod._ROOT = tmp
    return tmp


def teardown(tmp: Path) -> None:
    shutil.rmtree(tmp, ignore_errors=True)


# ── 1. Resolver precedence ─────────────────────────────────

def test_resolver_precedence():
    section("resolver precedence — agent project override beats global")
    tmp = fresh_root()
    try:
        (tmp / "agents").mkdir()
        (tmp / "agents" / "writer.md").write_text("GLOBAL", encoding="utf-8")
        (tmp / "projects" / "42" / "agents").mkdir(parents=True)
        (tmp / "projects" / "42" / "agents" / "writer.md").write_text("PROJECT", encoding="utf-8")

        p = resolve_agent_file("writer", 42)
        check("project override returned", p.read_text() == "PROJECT", str(p))

        p = resolve_agent_file("writer", 999)  # project without override
        check("fallback to global for other projects", p.read_text() == "GLOBAL")

        p = resolve_agent_file("writer", None)
        check("project_id=None → global", p.read_text() == "GLOBAL")

        try:
            resolve_agent_file("nobody", 42)
        except FileNotFoundError:
            check("missing agent raises FileNotFoundError", True)
        else:
            check("missing agent raises FileNotFoundError", False, "no exception")
    finally:
        teardown(tmp)


def test_pipeline_variant_fallback():
    section("resolver — pipeline variant fallback (global only)")
    tmp = fresh_root()
    try:
        (tmp / "pipelines").mkdir()
        (tmp / "pipelines" / "blog_generation.yaml").write_text("pipeline: blog_generation\nnodes: []", encoding="utf-8")

        # No blog.yaml, falls through to legacy _generation suffix
        p = resolve_pipeline_file("blog", None)
        check("global legacy fallback", p.name == "blog_generation.yaml", p.name)

        # Add strict blog.yaml — resolver should prefer it
        (tmp / "pipelines" / "blog.yaml").write_text("pipeline: blog\nnodes: []", encoding="utf-8")
        p = resolve_pipeline_file("blog", None)
        check("strict name beats legacy variant", p.name == "blog.yaml", p.name)

        # Project layer must NOT apply variant fallback
        (tmp / "projects" / "7" / "pipelines").mkdir(parents=True)
        (tmp / "projects" / "7" / "pipelines" / "blog_generation.yaml").write_text("x", encoding="utf-8")
        # No projects/7/pipelines/blog.yaml — should fall through to global
        p = resolve_pipeline_file("blog", 7)
        check(
            "project layer ignores variant; falls through to global",
            p == tmp / "pipelines" / "blog.yaml",
            str(p),
        )
    finally:
        teardown(tmp)


# ── 2. Name validation ─────────────────────────────────────

def test_name_validation():
    section("name validation")
    tmp = fresh_root()
    try:
        bad = ["..", "a/b", "a.b", "a b", "", "中文", "a..b", "/abs"]
        for n in bad:
            try:
                resolve_agent_file(n, None)
            except InvalidNameError:
                check(f"reject {n!r}", True)
            except Exception as e:
                check(f"reject {n!r}", False, f"wrong exception: {type(e).__name__}")
            else:
                check(f"reject {n!r}", False, "no exception")

        # Good names should pass validation (raise FileNotFoundError instead)
        good = ["writer_v2", "Agent-1", "abc", "A-B_C"]
        for n in good:
            try:
                resolve_agent_file(n, None)
            except FileNotFoundError:
                check(f"accept {n!r}", True)
            except InvalidNameError:
                check(f"accept {n!r}", False, "rejected by validation")
    finally:
        teardown(tmp)


# ── 3. CRUD round-trip ─────────────────────────────────────

def test_crud_agents():
    section("CRUD round-trip — agents")
    tmp = fresh_root()
    try:
        created = write_agent_global("alpha", "# alpha\n")
        check("write_agent_global returns True on create", created is True)

        created = write_agent_global("alpha", "# alpha v2\n")
        check("write_agent_global returns False on overwrite", created is False)

        check("read_agent returns content", read_agent("alpha", None) == "# alpha v2\n")
        check("list_agents_global", list_agents_global() == ["alpha"])

        created = write_agent_project("alpha", 1, "# project alpha\n")
        check("write_agent_project returns True on create", created is True)
        check("list_agents_project", list_agents_project(1) == ["alpha"])
        check(
            "read_agent with project_id resolves project layer",
            read_agent("alpha", 1) == "# project alpha\n",
        )

        delete_agent_project("alpha", 1)
        check("delete_agent_project", list_agents_project(1) == [])
        check(
            "after delete project, read falls back to global",
            read_agent("alpha", 1) == "# alpha v2\n",
        )

        # Auto-create parent directories for new project
        created = write_agent_project("beta", 99, "hi")
        check("write creates parent dirs for new project", created is True)
        check("new-project directory exists", (tmp / "projects" / "99" / "agents").is_dir())

        # Delete project on missing file raises
        try:
            delete_agent_project("nobody", 1)
        except FileNotFoundError:
            check("delete_agent_project on missing → FileNotFoundError", True)
        else:
            check("delete_agent_project on missing → FileNotFoundError", False, "no exception")
    finally:
        teardown(tmp)


def test_crud_pipelines():
    section("CRUD round-trip — pipelines")
    tmp = fresh_root()
    try:
        write_pipeline_global("proc", "pipeline: proc\nnodes: []\n")
        check("list_pipelines_global", list_pipelines_global() == ["proc"])
        check("read_pipeline", "pipeline: proc" in read_pipeline("proc", None))

        write_pipeline_project("proc", 3, "pipeline: proc\nnodes: [{name: x, role: general}]\n")
        check("list_pipelines_project", list_pipelines_project(3) == ["proc"])
        check(
            "project pipeline resolved when queried with project_id",
            "role: general" in read_pipeline("proc", 3),
        )

        # Pipeline delete never checks references
        delete_pipeline_global("proc")
        check("delete_pipeline_global unconditional", list_pipelines_global() == [])

        delete_pipeline_project("proc", 3)
        check("delete_pipeline_project", list_pipelines_project(3) == [])
    finally:
        teardown(tmp)


# ── 4. Merged view ─────────────────────────────────────────

def test_merged_view():
    section("merged view — three-state classification")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        write_agent_global("researcher", "G")
        write_agent_project("writer", 42, "P")   # project-override
        write_agent_project("analyst", 42, "P")  # project-only

        view = merged_agents_view(42)
        names = {row["name"]: row["source"] for row in view}
        check("writer is project-override", names.get("writer") == "project-override")
        check("researcher is global", names.get("researcher") == "global")
        check("analyst is project-only", names.get("analyst") == "project-only")
        check("view is sorted", [row["name"] for row in view] == ["analyst", "researcher", "writer"])

        # Empty project: all global
        view2 = merged_agents_view(999)
        check("empty project shows only global items", all(r["source"] == "global" for r in view2))
    finally:
        teardown(tmp)


# ── 5. Reference scanner ──────────────────────────────────

def test_reference_scanner():
    section("reference scanner — global pipelines")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        write_pipeline_global(
            "blog",
            "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n  - name: r\n    role: reviewer\n",
        )

        refs = find_agent_references_global("writer")
        check(
            "global pipeline reference detected",
            any(r["project_id"] is None and r["pipeline"] == "blog" for r in refs),
            str(refs),
        )

        refs = find_agent_references_global("nobody")
        check("no refs for unreferenced agent", refs == [])

    finally:
        teardown(tmp)


def test_reference_scanner_project():
    section("reference scanner — project pipelines honor override shield")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        # Project 42 references writer in its own pipeline, but also has its own writer override
        write_agent_project("writer", 42, "P")
        write_pipeline_project(
            "blog", 42,
            "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n",
        )
        # Project 7 references writer but has NO override — should show up
        write_pipeline_project(
            "blog", 7,
            "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n",
        )

        refs = find_agent_references_global("writer")
        pids = [r["project_id"] for r in refs]
        check("project 42 shielded by override", 42 not in pids)
        check("project 7 not shielded", 7 in pids)
    finally:
        teardown(tmp)


def test_reference_scanner_malformed():
    section("reference scanner — tolerates malformed yaml")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        (tmp / "pipelines").mkdir(exist_ok=True)
        (tmp / "pipelines" / "broken.yaml").write_text(
            "this is: [unbalanced", encoding="utf-8"
        )
        # No valid reference anywhere
        refs = find_agent_references_global("writer")
        check("malformed file contributes zero refs", refs == [])
    finally:
        teardown(tmp)


def test_reference_scanner_non_numeric_project():
    section("reference scanner — non-numeric project dir skipped")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        (tmp / "projects" / "not_a_number" / "pipelines").mkdir(parents=True)
        (tmp / "projects" / "not_a_number" / "pipelines" / "blog.yaml").write_text(
            "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n",
            encoding="utf-8",
        )
        refs = find_agent_references_global("writer")
        check("non-numeric project dir skipped", refs == [])
    finally:
        teardown(tmp)


# ── 6. delete_agent_global behavior ───────────────────────

def test_delete_agent_global_blocked():
    section("delete_agent_global — blocked by reference")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        write_pipeline_global(
            "blog",
            "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n",
        )
        try:
            delete_agent_global("writer")
        except AgentInUseError as e:
            check("AgentInUseError raised", True)
            check("references populated", len(e.references) >= 1, str(e.references))
        else:
            check("AgentInUseError raised", False, "no exception")

        check("global file still present", (tmp / "agents" / "writer.md").is_file())
    finally:
        teardown(tmp)


def test_delete_agent_global_allowed():
    section("delete_agent_global — allowed when no refs")
    tmp = fresh_root()
    try:
        write_agent_global("writer", "G")
        delete_agent_global("writer")
        check("global file removed", not (tmp / "agents" / "writer.md").is_file())
    finally:
        teardown(tmp)


def test_delete_agent_global_missing():
    section("delete_agent_global — missing → FileNotFoundError")
    tmp = fresh_root()
    try:
        try:
            delete_agent_global("nobody")
        except FileNotFoundError:
            check("FileNotFoundError on missing", True)
        else:
            check("FileNotFoundError on missing", False, "no exception")
    finally:
        teardown(tmp)


# ── Run ────────────────────────────────────────────────────


def main() -> None:
    original_root = layered_mod._ROOT
    try:
        test_resolver_precedence()
        test_pipeline_variant_fallback()
        test_name_validation()
        test_crud_agents()
        test_crud_pipelines()
        test_merged_view()
        test_reference_scanner()
        test_reference_scanner_project()
        test_reference_scanner_malformed()
        test_reference_scanner_non_numeric_project()
        test_delete_agent_global_blocked()
        test_delete_agent_global_allowed()
        test_delete_agent_global_missing()
    finally:
        layered_mod._ROOT = original_root

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
