"""Unit tests for telemetry contextvar propagation.

Verifies that current_turn_id / current_spawn_id / current_run_id behave as
expected under asyncio.create_task and that resets return to prior values.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telemetry.collector import (
    current_run_id,
    current_spawn_id,
    current_turn_id,
)

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}")


async def _t_set_reset_token():
    print("\n=== set / reset via token ===")
    check("initially None", current_turn_id.get() is None)
    tok = current_turn_id.set("T1")
    check("set to T1", current_turn_id.get() == "T1")
    current_turn_id.reset(tok)
    check("reset back to None", current_turn_id.get() is None)


async def _t_concurrent_tasks_isolated():
    print("\n=== concurrent tasks have isolated contextvars ===")
    results: dict[str, str | None] = {}

    async def worker(name: str, value: str):
        tok = current_turn_id.set(value)
        try:
            await asyncio.sleep(0.01)
            results[name] = current_turn_id.get()
        finally:
            current_turn_id.reset(tok)

    await asyncio.gather(
        worker("a", "T-A"),
        worker("b", "T-B"),
        worker("c", "T-C"),
    )
    check("task a saw T-A", results.get("a") == "T-A")
    check("task b saw T-B", results.get("b") == "T-B")
    check("task c saw T-C", results.get("c") == "T-C")


async def _t_create_task_inherits():
    print("\n=== asyncio.create_task inherits contextvar snapshot ===")
    inherited: dict[str, str | None] = {}

    async def child():
        inherited["turn"] = current_turn_id.get()
        inherited["spawn"] = current_spawn_id.get()

    tok_turn = current_turn_id.set("T-PARENT")
    tok_spawn = current_spawn_id.set("SPAWN-1")
    try:
        task = asyncio.create_task(child())
        await task
    finally:
        current_turn_id.reset(tok_turn)
        current_spawn_id.reset(tok_spawn)

    check("child inherited parent turn_id", inherited.get("turn") == "T-PARENT")
    check("child inherited parent spawn_id", inherited.get("spawn") == "SPAWN-1")


async def _t_parent_changes_after_spawn():
    print("\n=== parent changes after spawn are NOT reflected in child ===")
    observed: dict[str, str | None] = {}

    async def child():
        await asyncio.sleep(0.05)
        observed["turn"] = current_turn_id.get()

    tok = current_turn_id.set("T-BEFORE")
    task = asyncio.create_task(child())
    current_turn_id.set("T-AFTER")  # parent changes after task creation
    await task
    current_turn_id.reset(tok)

    check("child kept its snapshot (T-BEFORE)", observed.get("turn") == "T-BEFORE")


async def _t_multiple_contextvars_independent():
    print("\n=== turn/spawn/run contextvars are independent ===")
    tok_t = current_turn_id.set("T1")
    tok_s = current_spawn_id.set("S1")
    tok_r = current_run_id.set("R1")
    try:
        check("turn=T1", current_turn_id.get() == "T1")
        check("spawn=S1", current_spawn_id.get() == "S1")
        check("run=R1", current_run_id.get() == "R1")
    finally:
        current_run_id.reset(tok_r)
        current_spawn_id.reset(tok_s)
        current_turn_id.reset(tok_t)
    check("all reset", current_turn_id.get() is None
                       and current_spawn_id.get() is None
                       and current_run_id.get() is None)


async def _run_all() -> None:
    await _t_set_reset_token()
    await _t_concurrent_tasks_isolated()
    await _t_create_task_inherits()
    await _t_parent_changes_after_spawn()
    await _t_multiple_contextvars_independent()


if __name__ == "__main__":
    asyncio.run(_run_all())
    print(f"\n{'=' * 50}")
    print(f"Passed: {passed} / {passed + failed}")
    if failed:
        print(f"Failed: {failed}")
        sys.exit(1)
    print("All tests passed.")
