"""Verification for src/jobs: Job lifecycle, queue semantics, registry CRUD, cleanup."""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.jobs import JobRegistry, get_registry
from src.jobs.job import Job
from src.jobs.registry import reset_registry


async def test_create_returns_pending_job():
    print("=== JobRegistry.create returns pending Job ===")
    reg = JobRegistry()
    job = reg.create(kind="ingest")
    assert job.id, f"Expected non-empty id, got {job.id!r}"
    assert job.kind == "ingest"
    assert job.status == "pending", f"Expected pending, got {job.status}"
    assert job.error is None
    assert job.finished_at is None
    assert job.last_event is None
    assert job.queue.empty()
    print(f"  job.id={job.id}, status={job.status}")
    print("  OK")


async def test_get_returns_same_instance():
    print("=== JobRegistry.get returns same instance ===")
    reg = JobRegistry()
    job = reg.create(kind="ingest")
    fetched = reg.get(job.id)
    assert fetched is job, "Expected same instance"
    assert reg.get("nonexistent") is None
    print("  OK")


async def test_list_returns_all_jobs():
    print("=== JobRegistry.list returns all jobs ===")
    reg = JobRegistry()
    j1 = reg.create()
    j2 = reg.create()
    j3 = reg.create()
    all_jobs = reg.list()
    assert len(all_jobs) == 3
    assert {j.id for j in all_jobs} == {j1.id, j2.id, j3.id}
    print(f"  3 jobs listed")
    print("  OK")


async def test_emit_running_event_transitions_status():
    print("=== Job.emit running event transitions pending → running ===")
    job = Job(kind="ingest")
    assert job.status == "pending"
    job.emit({"event": "parsing_started"})
    assert job.status == "running", f"Expected running, got {job.status}"
    assert job.last_event == {"event": "parsing_started"}
    assert job.queue.qsize() == 1
    item = job.queue.get_nowait()
    assert item == {"event": "parsing_started"}
    print("  OK")


async def test_emit_done_sets_finished_and_sentinel():
    print("=== Job.emit done sets status, finished_at, and enqueues sentinel ===")
    job = Job()
    job.emit({"event": "parsing_started"})
    _ = job.queue.get_nowait()  # drain

    job.emit({"event": "done", "chunks": 42})
    assert job.status == "done"
    assert job.finished_at is not None
    assert job.error is None
    assert job.last_event == {"event": "done", "chunks": 42}

    # Should have the done event followed by None sentinel
    e1 = job.queue.get_nowait()
    e2 = job.queue.get_nowait()
    assert e1 == {"event": "done", "chunks": 42}
    assert e2 is None, f"Expected None sentinel, got {e2}"
    print("  OK")


async def test_emit_failed_sets_error_and_sentinel():
    print("=== Job.emit failed sets error, finished_at, and enqueues sentinel ===")
    job = Job()
    job.emit({"event": "failed", "error": "API timeout"})
    assert job.status == "failed"
    assert job.error == "API timeout"
    assert job.finished_at is not None

    e1 = job.queue.get_nowait()
    e2 = job.queue.get_nowait()
    assert e1 == {"event": "failed", "error": "API timeout"}
    assert e2 is None
    print("  OK")


async def test_drop_oldest_on_full_queue():
    print("=== Job.emit drop-oldest on full queue ===")
    job = Job()
    # Default maxsize is 1000; flood it
    for i in range(1000):
        job.emit({"event": "embedding_progress", "done": i, "total": 2000})
    assert job.queue.qsize() == 1000

    # One more — should drop the oldest
    job.emit({"event": "embedding_progress", "done": 1000, "total": 2000})
    assert job.queue.qsize() == 1000

    # The oldest event (done=0) should be gone; first now is done=1
    first = job.queue.get_nowait()
    assert first["done"] == 1, f"Expected done=1 after drop, got done={first['done']}"
    print("  OK")


async def test_to_dict_excludes_queue():
    print("=== Job.to_dict serializable, excludes queue ===")
    job = Job(kind="ingest")
    job.emit({"event": "parsing_started"})
    d = job.to_dict()
    assert "queue" not in d
    assert d["id"] == job.id
    assert d["kind"] == "ingest"
    assert d["status"] == "running"
    assert d["error"] is None
    assert d["last_event"] == {"event": "parsing_started"}
    assert d["started_at"] is not None
    assert d["finished_at"] is None
    print("  OK")


async def test_cleanup_finished_only_removes_old_finished():
    print("=== JobRegistry.cleanup_finished only removes old finished jobs ===")
    reg = JobRegistry()

    # 1) Running job — never removed
    j_running = reg.create()
    j_running.emit({"event": "parsing_started"})
    assert j_running.status == "running"

    # 2) Just-finished job (1 hour ago)
    j_recent = reg.create()
    j_recent.emit({"event": "done", "chunks": 5})
    j_recent.finished_at = datetime.now(timezone.utc) - timedelta(hours=1)

    # 3) Old finished job (2 days ago)
    j_old = reg.create()
    j_old.emit({"event": "done", "chunks": 3})
    j_old.finished_at = datetime.now(timezone.utc) - timedelta(days=2)

    removed = await reg.cleanup_finished(max_age_sec=86400)  # 24h threshold
    assert removed == 1, f"Expected 1 removed, got {removed}"
    assert reg.get(j_running.id) is not None
    assert reg.get(j_recent.id) is not None
    assert reg.get(j_old.id) is None
    print(f"  removed 1, kept 2")
    print("  OK")


async def test_get_registry_singleton():
    print("=== get_registry returns singleton ===")
    reset_registry()
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2, "Expected singleton"
    reset_registry()
    print("  OK")


async def main():
    print("\n--- Jobs Registry Verification ---\n")
    await test_create_returns_pending_job()
    await test_get_returns_same_instance()
    await test_list_returns_all_jobs()
    await test_emit_running_event_transitions_status()
    await test_emit_done_sets_finished_and_sentinel()
    await test_emit_failed_sets_error_and_sentinel()
    await test_drop_oldest_on_full_queue()
    await test_to_dict_excludes_queue()
    await test_cleanup_finished_only_removes_old_finished()
    await test_get_registry_singleton()
    print("\n[PASS] All jobs registry tests passed!\n")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
