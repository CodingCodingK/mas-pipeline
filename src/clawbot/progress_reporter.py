"""ChatProgressReporter — subscribes to a pipeline run's event stream and
double-writes progress to the chat channel + the conversation history.

Three-event granularity (start / interrupt / done). Intermediate node
transitions are intentionally NOT pushed — too noisy for a group chat.

Lifecycle is owned by the Gateway (not SessionRunner): a reporter must
outlive the SessionRunner because pipeline runs commonly outlive a session's
idle window. The Gateway holds a `dict[run_id, ChatProgressReporter]`
registry; this class does not own its registry slot — the
`confirm_pending_run` tool registers it and the reporter task removes itself
on the `done` event.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.bus.message import OutboundMessage
from src.engine.run import (
    subscribe_pipeline_events,
    unsubscribe_pipeline_events,
)

if TYPE_CHECKING:
    from src.bus.bus import MessageBus

logger = logging.getLogger(__name__)


class ChatProgressReporter:
    """One-per-pipeline-run reporter task."""

    def __init__(
        self,
        *,
        run_id: str,
        channel: str,
        chat_id: str,
        conversation_id: int,
        bus: MessageBus,
        on_done: "callable | None" = None,
    ) -> None:
        self.run_id = run_id
        self.channel = channel
        self.chat_id = chat_id
        self.conversation_id = conversation_id
        self._bus = bus
        self._on_done = on_done
        self._task: asyncio.Task | None = None
        self._queue: asyncio.Queue | None = None

    def start(self) -> None:
        """Subscribe to the run's event stream and launch the consumer task."""
        if self._task is not None:
            return
        self._queue = subscribe_pipeline_events(self.run_id)
        self._task = asyncio.create_task(
            self._loop(), name=f"clawbot-reporter:{self.run_id}"
        )

    def stop(self) -> None:
        if self._queue is not None:
            unsubscribe_pipeline_events(self.run_id, self._queue)
            self._queue = None
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def wait_done(self) -> None:
        if self._task is not None:
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ── internals ──────────────────────────────────────────────────

    async def _loop(self) -> None:
        assert self._queue is not None
        try:
            while True:
                event = await self._queue.get()
                etype = event.get("type", "")
                text: str | None = None
                terminal = False

                if etype == "pipeline_start":
                    pipeline = event.get("pipeline", "?")
                    text = (
                        f"[run #{self.run_id}] started: {pipeline} "
                        f"({event.get('node_count', '?')} nodes)"
                    )
                elif etype == "interrupt":
                    node = event.get("node", "?")
                    text = (
                        f"[run #{self.run_id}] 卡在 {node} (review). "
                        f"回 /resume {self.run_id} approve 或 "
                        f"/resume {self.run_id} reject:<理由>"
                    )
                elif etype in ("pipeline_completed", "pipeline_failed"):
                    status = "completed" if etype == "pipeline_completed" else "failed"
                    summary = (event.get("summary") or event.get("error") or "")[:500]
                    text = f"[run #{self.run_id}] {status}: {summary}"
                    terminal = True

                if text:
                    await self._publish(text)

                if terminal:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "ChatProgressReporter for run %s crashed", self.run_id
            )
        finally:
            if self._queue is not None:
                unsubscribe_pipeline_events(self.run_id, self._queue)
                self._queue = None
            if self._on_done is not None:
                try:
                    self._on_done(self.run_id)
                except Exception:
                    logger.exception(
                        "ChatProgressReporter on_done callback raised"
                    )

    async def _publish(self, text: str) -> None:
        """Double-write: outbound queue + conversation history."""
        try:
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=self.channel,
                    chat_id=self.chat_id,
                    content=text,
                )
            )
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: publish_outbound failed", self.run_id
            )

        try:
            from src.session.manager import append_message

            await append_message(
                self.conversation_id,
                {
                    "role": "assistant",
                    "content": text,
                    "metadata": {
                        "source": "progress_reporter",
                        "run_id": self.run_id,
                    },
                },
            )
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: append_message failed", self.run_id
            )
