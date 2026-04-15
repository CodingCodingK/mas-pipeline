"""Gateway: consumes inbound messages, dispatches them through SessionRunner,
publishes outbound replies once the runner finishes the turn."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.bus.message import InboundMessage, OutboundMessage
from src.bus.session import refresh_session, resolve_session
from src.engine.session_registry import get_or_create_runner
from src.session.manager import append_message

if TYPE_CHECKING:
    from src.bus.bus import MessageBus

logger = logging.getLogger(__name__)

# Max time to wait for a SessionRunner to emit a `done` event for a bus turn.
# Deadman switch for crashed/stuck runners — see design.md Decision 4.
_BUS_SUBSCRIBER_TIMEOUT_SECONDS = 300.0

_NO_RESPONSE_PLACEHOLDER = "(no response)"


def _parse_resume_feedback(raw: str | None) -> tuple[dict | None, str | None]:
    """Parse the trailing text of a /resume command into the engine dict.

    The engine's interrupt_fn reads ``feedback.get("action")`` to decide
    approve / reject / edit; passing a raw string silently defaults to
    approve and drops any "reject:..." intent. This parser produces the
    dict form so reject/edit survive the gateway hop.

    Returns ``(feedback_dict, error_text)``. On parse failure the dict is
    None and the error is a user-facing hint; on success the error is None.
    """
    if raw is None or not raw.strip():
        return {"action": "approve"}, None

    text = raw.strip()
    lower = text.lower()

    if lower in ("approve", "ok", "y", "yes"):
        return {"action": "approve"}, None

    for prefix in ("reject:", "reject：", "reject "):
        if lower.startswith(prefix):
            reason = text[len(prefix):].strip()
            if not reason:
                return None, (
                    "reject 需要理由：/resume <run_id> reject:<理由>"
                )
            return {"action": "reject", "feedback": reason}, None
    if lower == "reject":
        return None, "reject 需要理由：/resume <run_id> reject:<理由>"

    for prefix in ("edit:", "edit：", "edit "):
        if lower.startswith(prefix):
            edited = text[len(prefix):].strip()
            if not edited:
                return None, (
                    "edit 需要新文本：/resume <run_id> edit:<新内容>"
                )
            return {"action": "edit", "edited": edited}, None
    if lower == "edit":
        return None, "edit 需要新文本：/resume <run_id> edit:<新内容>"

    return None, (
        f"无法识别 /resume 语法：{text!r}。"
        "支持 `approve` / `reject:<理由>` / `edit:<新文本>`，"
        "或直接在群里说“通过/打回 <理由>/改成 <文本>”让我帮你解析。"
    )


class Gateway:
    """Per-message dispatch gateway.

    For each non-`/resume` InboundMessage:
    1. Resolve ChatSession (Redis cache -> PG)
    2. Append user message to Conversation
    3. Obtain (or create) the SessionRunner for that session
    4. Subscribe, wake the runner, wait for its `done` event
    5. Read the latest assistant message and publish one OutboundMessage
    """

    def __init__(
        self,
        bus: MessageBus,
        project_id: int,
        role: str = "assistant",
        session_ttl_hours: int = 24,
    ) -> None:
        self._bus = bus
        self._project_id = project_id
        self._role = role  # kept for API compat; runner picks role via session.mode
        self._session_ttl_hours = session_ttl_hours
        self._running = False
        self._active_tasks: set[asyncio.Task] = set()

        # Wire the MessageBus into the clawbot reporter registry so
        # confirm_pending_run can launch ChatProgressReporter instances.
        from src.clawbot.reporter_registry import install_bus
        install_bus(bus)

    async def run(self) -> None:
        """Main loop: consume inbound, dispatch per message."""
        self._running = True
        logger.info("Gateway started (project_id=%d, role=%s)", self._project_id, self._role)

        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self._bus.consume_inbound(), timeout=1.0
                )
            except TimeoutError:
                continue

            # Launch task for cross-session concurrency. Intra-session ordering
            # is guaranteed by SessionRunner's main loop, not by gateway locks.
            task = asyncio.create_task(self._dispatch(msg))
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

    async def stop(self) -> None:
        self._running = False
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        # Cancel any clawbot progress reporters still streaming pipeline events.
        from src.clawbot.reporter_registry import clear_registry_for_shutdown
        clear_registry_for_shutdown()

    async def _dispatch(self, msg: InboundMessage) -> None:
        await self._process_message(msg)

    async def _process_message(self, msg: InboundMessage) -> None:
        """Dispatch one inbound message through the SessionRunner registry."""
        try:
            # /resume is pipeline-level and must bypass the SessionRunner path.
            if msg.content.strip().startswith("/resume"):
                await self._handle_resume(msg)
                return

            # 1. Resolve session — clawbot is the top-level group chat agent
            # in this process, so every new bus-originated session gets
            # mode="bus_chat". Existing sessions keep their stored mode.
            session = await resolve_session(
                session_key=msg.session_key,
                channel=msg.channel,
                chat_id=msg.chat_id,
                project_id=self._project_id,
                ttl_hours=self._session_ttl_hours,
                mode="bus_chat",
            )

            # 2. Append the user message so the runner will pick it up on wakeup.
            user_message: dict = {"role": "user", "content": msg.content}
            await append_message(session.conversation_id, user_message)

            # 3. Obtain runner (shared with REST path via the registry)
            runner, created = await get_or_create_runner(
                session_id=session.id,
                mode=session.mode,
                project_id=session.project_id,
                conversation_id=session.conversation_id,
            )

            if not created:
                runner.notify_new_message()

            # 4. Subscribe, wake, buffer text deltas until `done`
            response_text = await self._wait_for_turn(runner, session.id)
            if response_text is None:
                # Timeout path — already logged in _wait_for_turn. Drop silently.
                return

            # 5. Refresh session activity
            await refresh_session(msg.session_key, self._session_ttl_hours)

            # 6. Publish outbound
            await self._bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response_text,
                reply_to=msg.metadata.get("message_id"),
            ))

        except Exception as exc:
            logger.exception("Gateway error processing message from %s", msg.session_key)
            try:
                from src.telemetry import get_collector
                get_collector().record_error(
                    source="gateway",
                    error_type=type(exc).__name__,
                    message=str(exc).splitlines()[0][:500] if str(exc) else "",
                    context={
                        "session_key": msg.session_key,
                        "inbound_topic": msg.channel,
                    },
                )
            except Exception:
                logger.debug("Failed to record gateway error telemetry", exc_info=True)
            try:
                await self._bus.publish_outbound(OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Sorry, an error occurred while processing your message.",
                ))
            except Exception:
                logger.error("Failed to send error response", exc_info=True)

    async def _wait_for_turn(self, runner, session_id: int) -> str | None:
        """Attach as a subscriber, wake the runner, buffer text until `done`.

        Accumulates `text_delta` events and returns the concatenated text when
        the terminal `done` event arrives. Returns None if the runner fails to
        emit `done` within the idle-timeout window.

        Reading text directly from the event stream avoids racing against
        `SessionRunner._persist_new_messages`, which runs only AFTER the
        agent_loop async-for exits — i.e. after `done` has already been
        fanned out to subscribers.
        """
        queue = runner.add_subscriber()
        buffer: list[str] = []
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_BUS_SUBSCRIBER_TIMEOUT_SECONDS
                    )
                except TimeoutError:
                    logger.warning(
                        "Bus subscriber timeout on session %d after %.0fs",
                        session_id, _BUS_SUBSCRIBER_TIMEOUT_SECONDS,
                    )
                    return None
                if event.type == "text_delta":
                    if event.content:
                        buffer.append(event.content)
                elif event.type == "done":
                    text = "".join(buffer).strip()
                    return text or _NO_RESPONSE_PLACEHOLDER
        finally:
            runner.remove_subscriber(queue)

    async def _handle_resume(self, msg: InboundMessage) -> None:
        """Handle /resume command: find paused pipelines, resume them.

        Syntax:
            /resume              — list paused runs for this project, auto-resume if only one
            /resume <run_id>     — resume a specific run
            /resume <run_id> <feedback>  — resume with feedback
        """
        from src.engine.pipeline import get_pipeline_status, resume_pipeline

        parts = msg.content.strip().split(maxsplit=2)
        # parts[0] = "/resume", parts[1] = run_id (optional), parts[2] = feedback (optional)

        specified_run_id = parts[1] if len(parts) > 1 else None
        raw_feedback = parts[2] if len(parts) > 2 else None
        feedback, parse_error = _parse_resume_feedback(raw_feedback)
        if parse_error is not None:
            await self._bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=parse_error,
                reply_to=msg.metadata.get("message_id"),
            ))
            return

        try:
            if specified_run_id:
                # Resume a specific run
                status_info = await get_pipeline_status(specified_run_id)
                if status_info["status"] != "paused":
                    response = f"Run {specified_run_id} is not paused (status: {status_info['status']})."
                else:
                    # Look up pipeline_name from DB
                    run = await self._get_run(specified_run_id)
                    if not run or not run.pipeline:
                        response = f"Run {specified_run_id} not found or has no pipeline."
                    else:
                        result = await resume_pipeline(
                            pipeline_name=run.pipeline,
                            run_id=specified_run_id,
                            project_id=self._project_id,
                            feedback=feedback,
                        )
                        response = f"Pipeline resumed. Status: {result.status}"
                        if result.paused_at:
                            response += f" (paused at: {result.paused_at})"
            else:
                # List paused runs for this project
                paused_runs = await self._list_paused_runs()
                if not paused_runs:
                    response = "No paused pipelines found."
                elif len(paused_runs) == 1:
                    run = paused_runs[0]
                    result = await resume_pipeline(
                        pipeline_name=run.pipeline,
                        run_id=run.run_id,
                        project_id=self._project_id,
                        feedback=feedback,
                    )
                    response = f"Resumed pipeline '{run.pipeline}'. Status: {result.status}"
                    if result.paused_at:
                        response += f" (paused at: {result.paused_at})"
                else:
                    lines = ["Multiple paused pipelines found:"]
                    for run in paused_runs:
                        lines.append(f"  /resume {run.run_id}  — {run.pipeline}")
                    response = "\n".join(lines)

        except Exception as exc:
            logger.exception("Error handling /resume")
            response = f"Error resuming pipeline: {exc}"

        await self._bus.publish_outbound(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=response,
            reply_to=msg.metadata.get("message_id"),
        ))

    async def _list_paused_runs(self) -> list:
        """List all paused workflow runs for this project."""
        from sqlalchemy import select

        from src.db import get_db
        from src.engine.run import RunStatus
        from src.models import WorkflowRun

        async with get_db() as session:
            result = await session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.project_id == self._project_id,
                    WorkflowRun.status == RunStatus.PAUSED.value,
                    WorkflowRun.pipeline.isnot(None),
                ).order_by(WorkflowRun.id.desc())
            )
            return list(result.scalars().all())

    async def _get_run(self, run_id: str):
        """Get a workflow run by run_id."""
        from src.engine.run import get_run
        return await get_run(run_id)
