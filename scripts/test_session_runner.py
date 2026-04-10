"""Unit tests for SessionRunner: lifecycle, wakeup, fanout, idle exit, cleanup.

All DB / agent_loop / create_agent calls are mocked — these tests run with
no PG, no Redis, no LLM.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.session_runner import SessionRunner

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


# ── Helpers ─────────────────────────────────────────────────


def _make_state(messages=None):
    state = MagicMock()
    state.messages = list(messages or [])
    state.tool_context = MagicMock()
    state.tool_context.session_id = None
    state.tool_context.conversation_id = None
    state.running_agent_count = 0
    return state


async def _empty_loop(state):
    """agent_loop stub that yields nothing and returns immediately."""
    if False:
        yield  # pragma: no cover — make this an async generator


# ── Tests ───────────────────────────────────────────────────


async def _run_lifecycle_test():
    print("\n=== SessionRunner lifecycle ===")
    state = _make_state(messages=[{"role": "system", "content": "x"}])

    with patch(
        "src.agent.factory.create_agent", new_callable=AsyncMock, return_value=state
    ), patch(
        "src.bus.session.get_session_history",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "src.engine.session_runner.agent_loop", new=_empty_loop
    ), patch(
        "src.session.manager.append_message", new_callable=AsyncMock
    ), patch(
        "src.session.manager.get_messages", new_callable=AsyncMock, return_value=[]
    ), patch(
        "src.engine.session_registry.deregister", new_callable=AsyncMock
    ):
        runner = SessionRunner(
            session_id=42, mode="chat", project_id=1, conversation_id=99
        )
        # Squeeze idle window so test exits fast
        with patch(
            "src.engine.session_runner.get_settings"
        ) as mock_settings:
            mock_settings.return_value.session.idle_timeout_seconds = 0.1
            mock_settings.return_value.session.max_age_seconds = 60

            await runner.start()
            check("task started", runner._task is not None)
            check("session_id forwarded to tool_context", state.tool_context.session_id == 42)
            check(
                "conversation_id forwarded",
                state.tool_context.conversation_id == 99,
            )

            # Wait for idle exit
            await asyncio.wait_for(runner.wait_done(), timeout=3.0)
            check("runner exited cleanly on idle", runner.is_done)


async def _run_subscriber_test():
    print("\n=== SessionRunner subscriber fanout ===")
    runner = SessionRunner(
        session_id=1, mode="chat", project_id=1, conversation_id=1
    )

    q1 = runner.add_subscriber()
    q2 = runner.add_subscriber()
    check("two subscribers registered", len(runner.subscribers) == 2)

    fake_event = MagicMock()
    runner._fanout(fake_event)
    check("subscriber 1 got event", q1.qsize() == 1)
    check("subscriber 2 got event", q2.qsize() == 1)

    runner.remove_subscriber(q1)
    check("subscriber removed", len(runner.subscribers) == 1)


async def _run_wakeup_test():
    print("\n=== SessionRunner wakeup primitive ===")
    runner = SessionRunner(
        session_id=1, mode="chat", project_id=1, conversation_id=1
    )
    runner.state = _make_state()

    # No subscribers, no agents → idle window should return True (exit)
    runner.last_active_at = datetime.utcnow() - timedelta(seconds=120)
    exited = await runner._wait_for_wakeup(
        idle_timeout=0.05, max_age=timedelta(seconds=600)
    )
    check("idle with no subs returns exit=True", exited is True)

    # With subscribers → idle returns False (keep waiting)
    runner.add_subscriber()
    exited = await runner._wait_for_wakeup(
        idle_timeout=0.05, max_age=timedelta(seconds=600)
    )
    check("idle with subscriber stays alive", exited is False)


async def _run_max_age_test():
    print("\n=== SessionRunner max_age cap ===")
    runner = SessionRunner(
        session_id=1, mode="chat", project_id=1, conversation_id=1
    )
    runner.state = _make_state()
    runner.created_at = datetime.utcnow() - timedelta(hours=25)

    exited = await runner._wait_for_wakeup(
        idle_timeout=None, max_age=timedelta(hours=24)
    )
    check("max_age triggers exit", exited is True)


# ── Run all ────────────────────────────────────────────────


async def main():
    await _run_lifecycle_test()
    await _run_subscriber_test()
    await _run_wakeup_test()
    await _run_max_age_test()


if __name__ == "__main__":
    asyncio.run(main())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed:
        sys.exit(1)
    print("All checks passed!")
