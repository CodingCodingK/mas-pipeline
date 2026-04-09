"""Unit tests for src/channels/manager.py — ChannelManager lifecycle, outbound dispatch."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bus.bus import MessageBus
from src.bus.message import OutboundMessage
from src.channels.base import BaseChannel
from src.channels.manager import ChannelManager, _CHANNEL_REGISTRY

passed = 0
failed = 0


def check(name: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok {name}")
    else:
        failed += 1
        print(f"  FAIL {name}")


class MockChannel(BaseChannel):
    """Mock channel for testing."""

    def __init__(self, name, config, bus):
        super().__init__(name, config, bus)
        self.started = False
        self.stopped = False
        self.sent: list[OutboundMessage] = []
        self._start_error = None

    async def start(self) -> None:
        if self._start_error:
            raise self._start_error
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


# === ChannelManager: init with enabled channels ===

print("=== ChannelManager: init ===")

# Clear and inject mock registry
_CHANNEL_REGISTRY.clear()
_CHANNEL_REGISTRY["mock1"] = MockChannel
_CHANNEL_REGISTRY["mock2"] = MockChannel

bus = MessageBus()
config = {
    "mock1": {"enabled": True, "key": "val1"},
    "mock2": {"enabled": True, "key": "val2"},
}
mgr = ChannelManager(config, bus)
check("2 channels registered", len(mgr._channels) == 2)
check("mock1 present", "mock1" in mgr._channels)
check("mock2 present", "mock2" in mgr._channels)

# === ChannelManager: disabled channels skipped ===

print("\n=== ChannelManager: disabled channels skipped ===")

_CHANNEL_REGISTRY.clear()
_CHANNEL_REGISTRY["mock1"] = MockChannel
_CHANNEL_REGISTRY["mock2"] = MockChannel

config_partial = {
    "mock1": {"enabled": True},
    "mock2": {"enabled": False},
}
mgr2 = ChannelManager(config_partial, MessageBus())
check("only 1 channel", len(mgr2._channels) == 1)
check("mock1 enabled", "mock1" in mgr2._channels)
check("mock2 disabled", "mock2" not in mgr2._channels)

# === ChannelManager: no config → no channels ===

print("\n=== ChannelManager: no config ===")

_CHANNEL_REGISTRY.clear()
_CHANNEL_REGISTRY["mock1"] = MockChannel

mgr3 = ChannelManager({}, MessageBus())
check("0 channels with empty config", len(mgr3._channels) == 0)

# === start_all: starts all channels ===

print("\n=== start_all ===")


async def test_start_all():
    _CHANNEL_REGISTRY.clear()
    _CHANNEL_REGISTRY["mock1"] = MockChannel

    bus = MessageBus()
    mgr = ChannelManager({"mock1": {"enabled": True}}, bus)
    await mgr.start_all()
    ch = mgr._channels["mock1"]
    check("channel started", ch.started)


asyncio.run(test_start_all())

# === start_all: tolerates errors ===

print("\n=== start_all: error tolerance ===")


async def test_start_error():
    _CHANNEL_REGISTRY.clear()
    _CHANNEL_REGISTRY["mock1"] = MockChannel
    _CHANNEL_REGISTRY["mock2"] = MockChannel

    bus = MessageBus()
    config = {"mock1": {"enabled": True}, "mock2": {"enabled": True}}
    mgr = ChannelManager(config, bus)
    mgr._channels["mock1"]._start_error = RuntimeError("boom")

    # Should not raise despite mock1 failure
    await mgr.start_all()
    check("mock2 still started", mgr._channels["mock2"].started)


asyncio.run(test_start_error())

# === stop_all: stops all channels ===

print("\n=== stop_all ===")


async def test_stop_all():
    _CHANNEL_REGISTRY.clear()
    _CHANNEL_REGISTRY["mock1"] = MockChannel
    _CHANNEL_REGISTRY["mock2"] = MockChannel

    bus = MessageBus()
    config = {"mock1": {"enabled": True}, "mock2": {"enabled": True}}
    mgr = ChannelManager(config, bus)
    await mgr.start_all()
    await mgr.stop_all()

    check("mock1 stopped", mgr._channels["mock1"].stopped)
    check("mock2 stopped", mgr._channels["mock2"].stopped)
    check("running flag cleared", mgr._running is False)


asyncio.run(test_stop_all())

# === dispatch_outbound: routes to correct channel ===

print("\n=== dispatch_outbound: routing ===")


async def test_dispatch():
    _CHANNEL_REGISTRY.clear()
    _CHANNEL_REGISTRY["mock1"] = MockChannel
    _CHANNEL_REGISTRY["mock2"] = MockChannel

    bus = MessageBus()
    config = {"mock1": {"enabled": True}, "mock2": {"enabled": True}}
    mgr = ChannelManager(config, bus)

    # Queue messages for both channels
    await bus.publish_outbound(OutboundMessage(channel="mock1", chat_id="c1", content="hello"))
    await bus.publish_outbound(OutboundMessage(channel="mock2", chat_id="c2", content="world"))

    # Run dispatcher briefly
    task = asyncio.create_task(mgr.dispatch_outbound())
    await asyncio.sleep(0.15)
    mgr._running = False
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    ch1 = mgr._channels["mock1"]
    ch2 = mgr._channels["mock2"]
    check("mock1 got 1 message", len(ch1.sent) == 1)
    check("mock1 content", ch1.sent[0].content == "hello")
    check("mock2 got 1 message", len(ch2.sent) == 1)
    check("mock2 content", ch2.sent[0].content == "world")


asyncio.run(test_dispatch())

# === dispatch_outbound: unknown channel logged, not crash ===

print("\n=== dispatch_outbound: unknown channel ===")


async def test_dispatch_unknown():
    _CHANNEL_REGISTRY.clear()
    _CHANNEL_REGISTRY["mock1"] = MockChannel

    bus = MessageBus()
    mgr = ChannelManager({"mock1": {"enabled": True}}, bus)

    await bus.publish_outbound(OutboundMessage(channel="nonexistent", chat_id="c1", content="x"))
    await bus.publish_outbound(OutboundMessage(channel="mock1", chat_id="c1", content="ok"))

    task = asyncio.create_task(mgr.dispatch_outbound())
    await asyncio.sleep(0.15)
    mgr._running = False
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    ch1 = mgr._channels["mock1"]
    check("mock1 still got message", len(ch1.sent) == 1)
    check("unknown channel did not crash", True)


asyncio.run(test_dispatch_unknown())

# === start_all with no channels: just warns ===

print("\n=== start_all: no channels ===")


async def test_start_no_channels():
    _CHANNEL_REGISTRY.clear()
    _CHANNEL_REGISTRY["mock1"] = MockChannel

    bus = MessageBus()
    mgr = ChannelManager({}, bus)
    await mgr.start_all()  # Should not raise
    check("no channels is fine", len(mgr._channels) == 0)


asyncio.run(test_start_no_channels())


# Cleanup registry
_CHANNEL_REGISTRY.clear()

print(f"\n{'='*40}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
