"""Unit tests for src.engine.session_registry.

All SessionRunner construction is replaced with a lightweight FakeRunner so
the tests run with no PG, no Redis, no LLM.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import session_registry as reg

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)


# ── Fake runner ────────────────────────────────────────────


class FakeRunner:
    """Minimal stand-in for SessionRunner — exposes the surface the registry
    pokes at."""

    instances: list["FakeRunner"] = []

    def __init__(
        self,
        session_id: int,
        mode: str,
        project_id: int,
        conversation_id: int,
        *,
        start_delay: float = 0.0,
        wait_done_delay: float = 0.0,
    ) -> None:
        self.session_id = session_id
        self.mode = mode
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.start_delay = start_delay
        self.wait_done_delay = wait_done_delay

        self._done = False
        self.exit_requested = False
        self.cancelled = False
        self.subscribers: set = set()
        self.state = SimpleNamespace(running_agent_count=0)
        self.created_at = datetime.utcnow()
        self.last_active_at = datetime.utcnow()
        FakeRunner.instances.append(self)

    async def start(self) -> None:
        if self.start_delay:
            await asyncio.sleep(self.start_delay)

    @property
    def is_done(self) -> bool:
        return self._done

    async def wait_done(self) -> None:
        if self.wait_done_delay:
            await asyncio.sleep(self.wait_done_delay)
        self._done = True

    async def request_exit(self) -> None:
        self.exit_requested = True
        self._done = True

    def cancel(self) -> None:
        self.cancelled = True
        self._done = True


def _reset_registry() -> None:
    """Wipe the module-level dict between tests."""
    reg._session_runners.clear()
    FakeRunner.instances.clear()


def _patch_runner_class(**fake_kwargs):
    """Patch the SessionRunner symbol that get_or_create_runner imports."""
    def factory(*args, **kwargs):
        return FakeRunner(*args, **kwargs, **fake_kwargs)
    return patch("src.engine.session_runner.SessionRunner", side_effect=factory)


# ── Tests ──────────────────────────────────────────────────


async def test_idempotent_create():
    print("\n=== get_or_create_runner idempotent ===")
    _reset_registry()
    with _patch_runner_class():
        r1 = await reg.get_or_create_runner(
            session_id=1, mode="chat", project_id=10, conversation_id=100
        )
        r2 = await reg.get_or_create_runner(
            session_id=1, mode="chat", project_id=10, conversation_id=100
        )
        check("returns same instance on 2nd call", r1 is r2)
        check("only 1 fake constructed (1st kept)",
              len([f for f in FakeRunner.instances if not f.exit_requested]) == 1)


async def test_concurrent_create():
    print("\n=== get_or_create_runner concurrent race ===")
    _reset_registry()
    # Make start() take a tick so two coroutines can race the lock window.
    with _patch_runner_class(start_delay=0.05):
        results = await asyncio.gather(
            reg.get_or_create_runner(
                session_id=2, mode="chat", project_id=1, conversation_id=2
            ),
            reg.get_or_create_runner(
                session_id=2, mode="chat", project_id=1, conversation_id=2
            ),
        )
        check("both calls return the same winner", results[0] is results[1])
        # The loser should have been told to exit.
        losers = [f for f in FakeRunner.instances if f.exit_requested]
        check("loser had request_exit called", len(losers) == 1)


async def test_get_runner_lookup():
    print("\n=== get_runner lookup ===")
    _reset_registry()
    with _patch_runner_class():
        r = await reg.get_or_create_runner(
            session_id=3, mode="chat", project_id=1, conversation_id=3
        )
        check("get_runner finds existing", reg.get_runner(3) is r)
        check("get_runner returns None for missing", reg.get_runner(999) is None)


async def test_deregister():
    print("\n=== deregister ===")
    _reset_registry()
    with _patch_runner_class():
        await reg.get_or_create_runner(
            session_id=4, mode="chat", project_id=1, conversation_id=4
        )
        check("registered", reg.get_runner(4) is not None)
        await reg.deregister(4)
        check("removed after deregister", reg.get_runner(4) is None)
        # Idempotent: removing again must not raise
        await reg.deregister(4)
        check("deregister idempotent", reg.get_runner(4) is None)


async def test_done_runner_replaced():
    print("\n=== done runner is replaced on next create ===")
    _reset_registry()
    with _patch_runner_class():
        r1 = await reg.get_or_create_runner(
            session_id=5, mode="chat", project_id=1, conversation_id=5
        )
        r1._done = True  # simulate it crashed/exited
        r2 = await reg.get_or_create_runner(
            session_id=5, mode="chat", project_id=1, conversation_id=5
        )
        check("dead runner replaced", r2 is not r1)
        check("registry holds new runner", reg.get_runner(5) is r2)


async def test_shutdown_all_normal():
    print("\n=== shutdown_all normal path ===")
    _reset_registry()
    with _patch_runner_class():
        runners = []
        for sid in (10, 11, 12):
            r = await reg.get_or_create_runner(
                session_id=sid, mode="chat", project_id=1, conversation_id=sid
            )
            runners.append(r)
        await reg.shutdown_all(timeout_seconds=1.0)
        check("all runners had request_exit", all(r.exit_requested for r in runners))
        check("all runners marked done", all(r.is_done for r in runners))
        check("none cancelled (clean exit)", not any(r.cancelled for r in runners))


async def test_shutdown_all_timeout_cancels():
    print("\n=== shutdown_all timeout cancels stragglers ===")
    _reset_registry()
    with _patch_runner_class(wait_done_delay=2.0):
        # Override request_exit so wait_done_delay actually applies — default
        # request_exit marks done=True immediately, short-circuiting wait_done.
        # Build the runner manually so we can keep it "alive" for the wait.
        class StubbornRunner(FakeRunner):
            async def request_exit(self) -> None:
                self.exit_requested = True
                # NOTE: do NOT mark done here; let wait_done block.

            async def wait_done(self) -> None:
                await asyncio.sleep(self.wait_done_delay)
                self._done = True

        with patch(
            "src.engine.session_runner.SessionRunner",
            side_effect=lambda *a, **k: StubbornRunner(
                *a, **k, wait_done_delay=2.0
            ),
        ):
            r = await reg.get_or_create_runner(
                session_id=20, mode="chat", project_id=1, conversation_id=20
            )
            t0 = asyncio.get_event_loop().time()
            await reg.shutdown_all(timeout_seconds=0.1)
            elapsed = asyncio.get_event_loop().time() - t0
            check("shutdown returned within ~timeout", elapsed < 1.0,
                  f"elapsed={elapsed:.2f}s")
            check("straggler was cancelled", r.cancelled)


async def test_idle_gc_request_exit_on_max_age():
    print("\n=== _idle_gc_task: max_age triggers request_exit ===")
    _reset_registry()
    with _patch_runner_class():
        # Build runner directly so we can backdate created_at.
        r_old = FakeRunner(
            session_id=30, mode="chat", project_id=1, conversation_id=30
        )
        r_old.created_at = datetime.utcnow() - timedelta(hours=25)
        reg._session_runners[30] = r_old

        r_new = FakeRunner(
            session_id=31, mode="chat", project_id=1, conversation_id=31
        )
        reg._session_runners[31] = r_new

        # Drive a single sweep manually by calling the inner logic. Easiest:
        # patch sleep to a 0-arg fast-forward then cancel after one tick.
        from src.engine.session_registry import _idle_gc_task

        with patch(
            "src.engine.session_registry._GC_INTERVAL_SECONDS", 0.01
        ):
            task = asyncio.create_task(_idle_gc_task())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        check("old runner request_exit called", r_old.exit_requested)
        check("fresh runner left alone", not r_new.exit_requested)


async def test_idle_gc_request_exit_on_idle():
    print("\n=== _idle_gc_task: idle timeout triggers request_exit ===")
    _reset_registry()
    r = FakeRunner(
        session_id=40, mode="chat", project_id=1, conversation_id=40
    )
    # Old enough to be idle, but not max-age
    r.last_active_at = datetime.utcnow() - timedelta(seconds=3600)
    reg._session_runners[40] = r

    from src.engine.session_registry import _idle_gc_task

    with patch("src.engine.session_registry._GC_INTERVAL_SECONDS", 0.01):
        task = asyncio.create_task(_idle_gc_task())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    check("idle runner request_exit called", r.exit_requested)


async def test_idle_gc_skips_runners_with_subscribers():
    print("\n=== _idle_gc_task: subscribers keep runner alive ===")
    _reset_registry()
    r = FakeRunner(
        session_id=50, mode="chat", project_id=1, conversation_id=50
    )
    r.last_active_at = datetime.utcnow() - timedelta(seconds=3600)
    r.subscribers.add(object())  # has a live subscriber
    reg._session_runners[50] = r

    from src.engine.session_registry import _idle_gc_task

    with patch("src.engine.session_registry._GC_INTERVAL_SECONDS", 0.01):
        task = asyncio.create_task(_idle_gc_task())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    check("runner with subscriber not exited", not r.exit_requested)


# ── Run all ────────────────────────────────────────────────


async def main() -> None:
    await test_idempotent_create()
    await test_concurrent_create()
    await test_get_runner_lookup()
    await test_deregister()
    await test_done_runner_replaced()
    await test_shutdown_all_normal()
    await test_shutdown_all_timeout_cancels()
    await test_idle_gc_request_exit_on_max_age()
    await test_idle_gc_request_exit_on_idle()
    await test_idle_gc_skips_runners_with_subscribers()


if __name__ == "__main__":
    asyncio.run(main())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
