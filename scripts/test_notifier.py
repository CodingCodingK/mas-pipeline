"""Unit tests for Notifier (mocked bus + channels)."""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path
from unittest.mock import AsyncMock

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.events.bus import EventBus
from src.notify.events import Notification
from src.notify.notifier import NullNotifier, Notifier
from src.telemetry.events import EVENT_TYPE_PIPELINE, TelemetryEvent

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


class FakeChannel:
    def __init__(self, name: str, raise_exc: Exception | None = None) -> None:
        self.name = name
        self.received: list[Notification] = []
        self._raise = raise_exc

    async def deliver(self, notification: Notification) -> None:
        if self._raise is not None:
            raise self._raise
        self.received.append(notification)


def _make_prefs(prefs_map: dict[tuple[int, str], list[str]]):
    class _FakeSession:
        async def __aenter__(self_inner):
            return self_inner

        async def __aexit__(self_inner, *a):
            return None

    def factory():
        return _FakeSession()

    async def fake_get(user_id, event_type, session_factory):
        return list(prefs_map.get((user_id, event_type), []))

    async def fake_get_all(user_id, session_factory):
        return {
            et: list(ch)
            for (uid, et), ch in prefs_map.items()
            if uid == user_id
        }

    return factory, fake_get, fake_get_all


def _pipeline_end_event(project_id: int, success: bool) -> TelemetryEvent:
    return TelemetryEvent(
        event_type=EVENT_TYPE_PIPELINE,
        project_id=project_id,
        payload={
            "pipeline_event_type": "pipeline_end",
            "pipeline_name": "p",
            "success": success,
        },
        run_id="run-1",
    )


async def _drain(bus: EventBus, notifier: Notifier) -> None:
    for _ in range(50):
        await asyncio.sleep(0.02)
        if notifier._queue.empty():
            break


async def _stop(notifier: Notifier) -> None:
    await notifier.stop(timeout_seconds=2.0)


async def test_matched_event_delivers_to_enabled_channels() -> None:
    print("\n-- Notifier dispatches to enabled channels --")
    from src.notify import preferences as prefs_module

    bus = EventBus(queue_size=50)
    sse = FakeChannel("sse")
    wechat = FakeChannel("wechat")
    discord = FakeChannel("discord")

    factory, fake_get, fake_get_all = _make_prefs(
        {(1, "run_failed"): ["sse", "wechat"]}
    )
    prefs_module.get = fake_get  # type: ignore[assignment]
    prefs_module.get_all = fake_get_all  # type: ignore[assignment]

    async def resolve(pid: int) -> int | None:
        return 1 if pid == 42 else None

    notifier = Notifier(
        bus=bus,
        channels=[sse, wechat, discord],
        rules=None,
        session_factory=factory,
        resolve_user=resolve,
        queue_size=50,
    )
    await notifier.start()
    bus.emit(_pipeline_end_event(42, success=False))
    await _drain(bus, notifier)
    await _stop(notifier)

    check("sse received", len(sse.received) == 1 and sse.received[0].event_type == "run_failed")
    check("wechat received", len(wechat.received) == 1)
    check("discord NOT received", len(discord.received) == 0)


async def test_no_prefs_drops_notification() -> None:
    print("\n-- Notifier drops when user has no prefs --")
    from src.notify import preferences as prefs_module

    bus = EventBus(queue_size=50)
    sse = FakeChannel("sse")

    factory, fake_get, fake_get_all = _make_prefs({})
    prefs_module.get = fake_get  # type: ignore[assignment]

    async def resolve(pid: int) -> int | None:
        return 1

    notifier = Notifier(
        bus=bus, channels=[sse], rules=None,
        session_factory=factory, resolve_user=resolve, queue_size=50,
    )
    await notifier.start()
    bus.emit(_pipeline_end_event(1, success=True))
    await _drain(bus, notifier)
    await _stop(notifier)
    check("no delivery", len(sse.received) == 0)


async def test_rule_exception_isolated() -> None:
    print("\n-- Rule raising does not poison loop --")
    from src.notify import preferences as prefs_module
    from src.notify.rules import default_rules

    bus = EventBus(queue_size=50)
    sse = FakeChannel("sse")

    factory, fake_get, _ = _make_prefs(
        {(1, "run_completed"): ["sse"]}
    )
    prefs_module.get = fake_get  # type: ignore[assignment]

    def bad_rule(event, user_id):
        raise ValueError("kaboom")

    rules = [bad_rule] + default_rules()

    async def resolve(pid: int) -> int | None:
        return 1

    notifier = Notifier(
        bus=bus, channels=[sse], rules=rules,
        session_factory=factory, resolve_user=resolve, queue_size=50,
    )
    await notifier.start()
    bus.emit(_pipeline_end_event(1, success=True))
    await _drain(bus, notifier)
    await _stop(notifier)
    check("good rule still fired despite bad rule", len(sse.received) == 1)


async def test_channel_failure_isolated() -> None:
    print("\n-- Channel raising does not block siblings --")
    from src.notify import preferences as prefs_module

    bus = EventBus(queue_size=50)
    failing = FakeChannel("sse", raise_exc=RuntimeError("disk full"))
    good = FakeChannel("wechat")

    factory, fake_get, _ = _make_prefs(
        {(1, "run_completed"): ["sse", "wechat"]}
    )
    prefs_module.get = fake_get  # type: ignore[assignment]

    async def resolve(pid: int) -> int | None:
        return 1

    notifier = Notifier(
        bus=bus, channels=[failing, good], rules=None,
        session_factory=factory, resolve_user=resolve, queue_size=50,
    )
    await notifier.start()
    bus.emit(_pipeline_end_event(1, success=True))
    await _drain(bus, notifier)
    await _stop(notifier)
    check("good channel still received", len(good.received) == 1)


async def test_multi_user_isolation() -> None:
    print("\n-- Multi-user preference isolation --")
    from src.notify import preferences as prefs_module

    bus = EventBus(queue_size=50)
    sse = FakeChannel("sse")
    wechat = FakeChannel("wechat")

    factory, fake_get, _ = _make_prefs(
        {(1, "run_completed"): ["sse"], (2, "run_completed"): ["wechat"]}
    )
    prefs_module.get = fake_get  # type: ignore[assignment]

    async def resolve(pid: int) -> int | None:
        return pid  # project_id happens to equal user_id

    notifier = Notifier(
        bus=bus, channels=[sse, wechat], rules=None,
        session_factory=factory, resolve_user=resolve, queue_size=50,
    )
    await notifier.start()
    bus.emit(_pipeline_end_event(1, success=True))
    bus.emit(_pipeline_end_event(2, success=True))
    await _drain(bus, notifier)
    await _stop(notifier)
    check(
        "sse saw only user 1",
        len(sse.received) == 1 and sse.received[0].user_id == 1,
    )
    check(
        "wechat saw only user 2",
        len(wechat.received) == 1 and wechat.received[0].user_id == 2,
    )


async def test_stop_cancels_loop() -> None:
    print("\n-- stop cancels loop within timeout --")
    bus = EventBus(queue_size=10)

    async def noop_resolve(pid: int) -> int | None:
        return None

    notifier = Notifier(
        bus=bus, channels=[], rules=None,
        session_factory=lambda: None, resolve_user=noop_resolve, queue_size=10,
    )
    await notifier.start()
    await notifier.stop(timeout_seconds=1.0)
    check("task cleared", notifier._task is None)


async def test_null_notifier_noop() -> None:
    print("\n-- NullNotifier is a no-op --")
    n = NullNotifier()
    await n.start()
    await n.stop()
    check("no exception", True)


async def main() -> int:
    await test_matched_event_delivers_to_enabled_channels()
    await test_no_prefs_drops_notification()
    await test_rule_exception_isolated()
    await test_channel_failure_isolated()
    await test_multi_user_isolation()
    await test_stop_cancels_loop()
    await test_null_notifier_noop()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
