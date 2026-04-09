"""Gateway CLI entry point: start all channels + gateway main loop."""

from __future__ import annotations

import asyncio
import logging
import signal

from src.bus.bus import MessageBus
from src.bus.gateway import Gateway
from src.channels.manager import ChannelManager
from src.db import close_db, init_db, get_redis
from src.project.config import get_settings

logger = logging.getLogger(__name__)

_LOCK_KEY = "gateway:lock"
_LOCK_TTL = 30  # seconds, renewed by heartbeat


async def _acquire_lock() -> bool:
    """Try to acquire the gateway singleton lock in Redis. Returns True if acquired."""
    redis = get_redis()
    acquired = await redis.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL)
    return acquired is not None


async def _release_lock() -> None:
    """Release the gateway singleton lock."""
    redis = get_redis()
    await redis.delete(_LOCK_KEY)


async def _lock_heartbeat(stop_event: asyncio.Event) -> None:
    """Renew the lock TTL periodically until stop_event is set."""
    redis = get_redis()
    interval = _LOCK_TTL // 3  # renew at 1/3 of TTL
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
        if not stop_event.is_set():
            await redis.expire(_LOCK_KEY, _LOCK_TTL)


async def run_gateway() -> None:
    """Main entry point: init DB, start channels + gateway, run until shutdown."""
    settings = get_settings()
    channels_cfg = settings.channels

    # Init DB + Redis
    await init_db()
    logger.info("Database and Redis connected")

    # Singleton lock — prevent multiple gateway instances
    if not await _acquire_lock():
        logger.error("Another gateway instance is already running")
        await close_db()
        return

    # Create bus
    bus = MessageBus()

    # Create channel manager
    channel_mgr = ChannelManager(
        channels_config={
            "discord": channels_cfg.discord,
            "qq": channels_cfg.qq,
            "wechat": channels_cfg.wechat,
        },
        bus=bus,
    )

    # Create gateway
    gateway = Gateway(
        bus=bus,
        project_id=channels_cfg.project_id,
        role=channels_cfg.role,
        max_history=channels_cfg.max_history,
        session_ttl_hours=channels_cfg.session_ttl_hours,
    )

    # Graceful shutdown handler
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler
            pass

    # Start lock heartbeat
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(_lock_heartbeat(heartbeat_stop))

    try:
        # Run all components concurrently (start_all blocks for long-lived channels)
        channels_task = asyncio.create_task(channel_mgr.start_all())
        gateway_task = asyncio.create_task(gateway.run())
        dispatch_task = asyncio.create_task(channel_mgr.dispatch_outbound())

        # Wait for shutdown signal or KeyboardInterrupt
        await shutdown_event.wait()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        logger.info("Shutting down gateway...")

        # Stop lock heartbeat and release lock
        heartbeat_stop.set()
        await heartbeat_task
        await _release_lock()

        # Stop gateway
        await gateway.stop()

        # Stop channels (sets _running=False, breaks channel start loops)
        await channel_mgr.stop_all()

        # Cancel remaining tasks
        for t in [channels_task, gateway_task, dispatch_task]:
            if not t.done():
                t.cancel()
        await asyncio.gather(channels_task, gateway_task, dispatch_task, return_exceptions=True)

        # Close DB/Redis
        await close_db()
        logger.info("Gateway shutdown complete")


def main() -> None:
    """CLI entry point."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Windows: psycopg requires SelectorEventLoop, not ProactorEventLoop
    if sys.platform == "win32":
        asyncio.run(run_gateway(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(run_gateway())


if __name__ == "__main__":
    main()
