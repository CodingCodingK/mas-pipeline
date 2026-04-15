"""Unit tests for src/tools/builtins/project_info.py.

Covers all 8 scenarios from openspec/changes/add-project-info-tools/tasks.md §4:
- 4.1 GetCurrentProject happy path
- 4.2 GetCurrentProject project_id=None (no DB query)
- 4.3 ListProjectRuns default limit / status filter / limit clamp
- 4.4 ListProjectRuns cross-project isolation
- 4.5 GetRunDetails happy path with multiple agent_runs
- 4.6 GetRunDetails cross-project run_id -> not-found
- 4.7 GetRunDetails preview fallback chain (pure helper)
- 4.8 GetRunDetails preview truncation at 200 chars (pure helper)

Pure helpers (_extract_last_assistant_preview) are tested without DB.
Everything else hits a real Postgres via src.db.init_db, seeds rows under a
dedicated test user, and cleans up in a finally block.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete

from src.db import close_db, get_db, init_db
from src.models import AgentRun, Document, Project, WorkflowRun
from src.tools.base import ToolContext
from src.tools.builtins.project_info import (
    GetCurrentProjectTool,
    GetRunDetailsTool,
    ListProjectRunsTool,
    _extract_last_assistant_preview,
    _PREVIEW_MAX_CHARS,
)

TEST_USER_ID = 1

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


# ─────────────────────────── 4.7 / 4.8 pure helpers ──────────────────────


def test_preview_fallback_chain() -> None:
    print("\n=== 4.7 Preview fallback chain ===")

    # assistant present — string content
    msgs_str = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello world"},
    ]
    check(
        "assistant string content",
        _extract_last_assistant_preview(msgs_str, "fallback") == "hello world",
    )

    # assistant present — block content list
    msgs_blocks = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "part one "},
                {"type": "text", "text": "part two"},
            ],
        }
    ]
    check(
        "assistant block list content",
        _extract_last_assistant_preview(msgs_blocks, None) == "part one part two",
    )

    # assistant absent — falls back to result
    check(
        "falls back to result when no assistant",
        _extract_last_assistant_preview([{"role": "user", "content": "hi"}], "result text")
        == "result text",
    )

    # both empty — '(no output)'
    check("fallback (no output)", _extract_last_assistant_preview([], None) == "(no output)")
    check("fallback (no output) empty string", _extract_last_assistant_preview([], "") == "(no output)")

    # messages is not a list
    check(
        "non-list messages falls through",
        _extract_last_assistant_preview("garbage", "rescued") == "rescued",  # type: ignore[arg-type]
    )

    # Last assistant (not first) is picked
    msgs_multi = [
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "last"},
    ]
    check(
        "last assistant wins",
        _extract_last_assistant_preview(msgs_multi, None) == "last",
    )


def test_preview_truncation() -> None:
    print("\n=== 4.8 Preview truncation ===")
    long_text = "a" * 500
    preview = _extract_last_assistant_preview(
        [{"role": "assistant", "content": long_text}], None
    )
    check(
        f"truncated to {_PREVIEW_MAX_CHARS}+ellipsis",
        len(preview) <= _PREVIEW_MAX_CHARS + 4,
        f"got len={len(preview)}",
    )
    check("starts with original content", preview.startswith("a" * _PREVIEW_MAX_CHARS))
    check("ends with ellipsis", preview.endswith("…"))

    # exactly 200 chars — no truncation
    exact = "b" * _PREVIEW_MAX_CHARS
    p2 = _extract_last_assistant_preview([{"role": "assistant", "content": exact}], None)
    check("exact 200 not truncated", p2 == exact)


# ─────────────────────────── DB-backed tests ──────────────────────


async def seed_project(name: str, pipeline: str = "blog_generation") -> int:
    async with get_db() as session:
        p = Project(user_id=TEST_USER_ID, name=name, pipeline=pipeline, description=f"{name} desc")
        session.add(p)
        await session.flush()
        await session.commit()
        return p.id


async def seed_documents(project_id: int, n: int) -> None:
    async with get_db() as session:
        for i in range(n):
            session.add(
                Document(
                    project_id=project_id,
                    filename=f"doc_{i}.pdf",
                    file_type="pdf",
                )
            )
        await session.commit()


async def seed_run(
    project_id: int,
    run_id: str,
    status: str = "completed",
    started_offset_s: int = 0,
    duration_s: int = 10,
    pipeline: str = "blog_generation",
) -> int:
    """Seed one workflow_runs row and return its numeric id."""
    base = datetime(2026, 4, 15, 12, 0, 0)
    started = base + timedelta(seconds=started_offset_s)
    finished = started + timedelta(seconds=duration_s)
    async with get_db() as session:
        r = WorkflowRun(
            project_id=project_id,
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            started_at=started,
            finished_at=finished if status in ("completed", "failed") else None,
        )
        session.add(r)
        await session.flush()
        await session.commit()
        return r.id


async def seed_agent_run(
    workflow_id: int,
    role: str,
    status: str = "completed",
    messages: list | None = None,
    result: str | None = None,
    total_tokens: int = 0,
    tool_use_count: int = 0,
    duration_ms: int = 0,
) -> None:
    async with get_db() as session:
        session.add(
            AgentRun(
                run_id=workflow_id,
                role=role,
                status=status,
                messages=messages or [],
                result=result,
                total_tokens=total_tokens,
                tool_use_count=tool_use_count,
                duration_ms=duration_ms,
            )
        )
        await session.commit()


async def cleanup(project_ids: list[int]) -> None:
    async with get_db() as session:
        # delete agent_runs whose workflow_runs belong to test projects
        wr_ids_rows = await session.execute(
            WorkflowRun.__table__.select().where(WorkflowRun.project_id.in_(project_ids))
        )
        wr_ids = [row.id for row in wr_ids_rows]
        if wr_ids:
            await session.execute(delete(AgentRun).where(AgentRun.run_id.in_(wr_ids)))
        await session.execute(delete(WorkflowRun).where(WorkflowRun.project_id.in_(project_ids)))
        await session.execute(delete(Document).where(Document.project_id.in_(project_ids)))
        await session.execute(delete(Project).where(Project.id.in_(project_ids)))
        await session.commit()


async def test_get_current_project_happy(pid: int) -> None:
    print("\n=== 4.1 GetCurrentProject happy path ===")
    tool = GetCurrentProjectTool()
    ctx = ToolContext(agent_id="test", run_id="test", project_id=pid)
    res = await tool.call({}, ctx)
    check("success", res.success)
    out = res.output
    check("contains project_id", f"project_id: {pid}" in out)
    check("contains name", "name: PInfoTest-A" in out)
    check("contains pipeline", "pipeline: blog_generation" in out)
    check("contains document_count", "document_count: 3" in out, out)
    check("contains latest_run", "latest_run: run-a-2" in out, out)  # newest


async def test_get_current_project_no_context() -> None:
    print("\n=== 4.2 GetCurrentProject project_id=None ===")
    tool = GetCurrentProjectTool()
    res = await tool.call({}, ToolContext(agent_id="test", run_id="test", project_id=None))
    check("failure", res.success is False)
    check("error message", res.output == "Error: no project context available")


async def test_get_current_project_no_runs(pid_empty: int) -> None:
    print("\n=== 4.1b GetCurrentProject (no runs) ===")
    tool = GetCurrentProjectTool()
    res = await tool.call({}, ToolContext(agent_id="test", run_id="test", project_id=pid_empty))
    check("success", res.success)
    check("latest_run (none)", "latest_run: (none)" in res.output, res.output)
    check("document_count: 0", "document_count: 0" in res.output)


async def test_list_runs_default_and_clamp(pid: int) -> None:
    print("\n=== 4.3 ListProjectRuns default/status/clamp ===")
    tool = ListProjectRunsTool()
    ctx = ToolContext(agent_id="test", run_id="test", project_id=pid)

    # default — returns both seeded runs, newest first
    res = await tool.call({}, ctx)
    check("success default", res.success)
    lines = [ln for ln in res.output.splitlines() if ln]
    check("2 rows", len(lines) == 2, f"got {len(lines)}: {res.output}")
    check("newest first (run-a-2)", lines[0].startswith("run-a-2"), lines[0])
    check("duration_s rendered", "| 10s" in lines[0])

    # status filter: only 'completed' — both seeded runs are completed
    res_c = await tool.call({"status": "completed"}, ctx)
    lines_c = [ln for ln in res_c.output.splitlines() if ln]
    check("status filter 2 completed rows", len(lines_c) == 2, f"got {lines_c}")
    check("status filter returns completed", all("completed" in ln for ln in lines_c))

    # status filter: 'failed' — should return (no runs)
    res_f = await tool.call({"status": "failed"}, ctx)
    check("no failed runs -> (no runs)", res_f.output == "(no runs)", res_f.output)

    # clamp: limit=500 -> clamped to 50; can't see clamping directly but
    # request must succeed and not error.
    res_big = await tool.call({"limit": 500}, ctx)
    check("limit=500 succeeds (clamped)", res_big.success)

    # clamp: limit=0 -> clamped to 1
    res_zero = await tool.call({"limit": 0}, ctx)
    lines_z = [ln for ln in res_zero.output.splitlines() if ln]
    check("limit=0 clamps to 1 row", len(lines_z) == 1, f"got {len(lines_z)}")

    # clamp: limit=-1 -> clamped to 1
    res_neg = await tool.call({"limit": -1}, ctx)
    lines_n = [ln for ln in res_neg.output.splitlines() if ln]
    check("limit=-1 clamps to 1 row", len(lines_n) == 1)


async def test_list_runs_cross_project_isolation(pid_a: int, pid_b: int) -> None:
    print("\n=== 4.4 ListProjectRuns cross-project isolation ===")
    tool = ListProjectRunsTool()
    res_a = await tool.call({}, ToolContext(agent_id="test", run_id="test", project_id=pid_a))
    check("project A does not see B runs", "run-b-1" not in res_a.output, res_a.output)
    res_b = await tool.call({}, ToolContext(agent_id="test", run_id="test", project_id=pid_b))
    check("project B does not see A runs", "run-a-1" not in res_b.output, res_b.output)
    check("project B sees its own run", "run-b-1" in res_b.output, res_b.output)


async def test_get_run_details_happy(pid: int) -> None:
    print("\n=== 4.5 GetRunDetails happy path ===")
    tool = GetRunDetailsTool()
    res = await tool.call({"run_id": "run-a-1"}, ToolContext(agent_id="test", run_id="test", project_id=pid))
    check("success", res.success, res.output)
    lines = res.output.splitlines()
    check("header line present", lines[0].startswith("run_id: run-a-1"), lines[0])
    node_lines = lines[1:]
    check("3 agent_run lines", len(node_lines) == 3, f"got {len(node_lines)}: {node_lines}")
    check("writer role present", any("writer" in ln for ln in node_lines))
    check("preview contains assistant text", any("final writer output" in ln for ln in node_lines))


async def test_get_run_details_cross_project(pid_a: int, pid_b: int) -> None:
    print("\n=== 4.6 GetRunDetails cross-project rejected as not-found ===")
    tool = GetRunDetailsTool()
    # run-b-1 belongs to project B; calling from project A must fail
    res = await tool.call({"run_id": "run-b-1"}, ToolContext(agent_id="test", run_id="test", project_id=pid_a))
    check("failure", res.success is False, res.output)
    check(
        "not-found message",
        res.output == "Error: run 'run-b-1' not found in current project",
        res.output,
    )

    # same tool from correct project must succeed
    res_ok = await tool.call({"run_id": "run-b-1"}, ToolContext(agent_id="test", run_id="test", project_id=pid_b))
    check("correct project succeeds", res_ok.success, res_ok.output)


async def test_get_run_details_no_context() -> None:
    print("\n=== 4.6b GetRunDetails no project context ===")
    tool = GetRunDetailsTool()
    res = await tool.call({"run_id": "anything"}, ToolContext(agent_id="test", run_id="test", project_id=None))
    check("failure", res.success is False)
    check("no-context error", res.output == "Error: no project context available")


async def main() -> int:
    # pure helpers first — no DB needed
    test_preview_fallback_chain()
    test_preview_truncation()

    await init_db()

    pid_a: int | None = None
    pid_b: int | None = None
    pid_empty: int | None = None
    try:
        pid_a = await seed_project("PInfoTest-A")
        pid_b = await seed_project("PInfoTest-B", pipeline="blog_with_review")
        pid_empty = await seed_project("PInfoTest-Empty")

        await seed_documents(pid_a, 3)

        # Project A: two runs (run-a-1 older, run-a-2 newer), run-a-1 has 3 agent_runs
        wf_a1 = await seed_run(pid_a, "run-a-1", status="completed", started_offset_s=0)
        await seed_run(pid_a, "run-a-2", status="completed", started_offset_s=60)

        await seed_agent_run(
            wf_a1,
            role="researcher",
            messages=[{"role": "assistant", "content": "researcher done"}],
            total_tokens=100,
            tool_use_count=2,
            duration_ms=1500,
        )
        await seed_agent_run(
            wf_a1,
            role="writer",
            messages=[
                {"role": "user", "content": "write"},
                {"role": "assistant", "content": "final writer output"},
            ],
            total_tokens=200,
            tool_use_count=0,
            duration_ms=3000,
        )
        await seed_agent_run(
            wf_a1,
            role="reviewer",
            messages=[],
            result="reviewer fallback result",
            total_tokens=50,
        )

        # Project B: one run
        await seed_run(pid_b, "run-b-1", status="running", started_offset_s=0)

        await test_get_current_project_happy(pid_a)
        await test_get_current_project_no_context()
        await test_get_current_project_no_runs(pid_empty)
        await test_list_runs_default_and_clamp(pid_a)
        await test_list_runs_cross_project_isolation(pid_a, pid_b)
        await test_get_run_details_happy(pid_a)
        await test_get_run_details_cross_project(pid_a, pid_b)
        await test_get_run_details_no_context()
    finally:
        ids = [x for x in (pid_a, pid_b, pid_empty) if x is not None]
        if ids:
            await cleanup(ids)
        await close_db()

    print(f"\n--- Results: {passed} passed, {failed} failed ---\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop))
