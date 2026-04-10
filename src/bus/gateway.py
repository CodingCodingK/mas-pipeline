"""Gateway: consumes inbound messages, runs agent per message, publishes outbound."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.bus.bus import MessageBus
from src.bus.message import InboundMessage, OutboundMessage
from src.bus.session import get_session_history, refresh_session, resolve_session
from src.session.manager import append_message

logger = logging.getLogger(__name__)


class Gateway:
    """Per-message dispatch gateway.

    For each InboundMessage:
    1. Resolve ChatSession (Redis cache -> PG)
    2. Load conversation history
    3. Create agent, inject history, run to completion
    4. Save messages, publish outbound response
    """

    def __init__(
        self,
        bus: MessageBus,
        project_id: int,
        role: str = "assistant",
        max_history: int = 50,
        session_ttl_hours: int = 24,
    ) -> None:
        self._bus = bus
        self._project_id = project_id
        self._role = role
        self._max_history = max_history
        self._session_ttl_hours = session_ttl_hours
        self._running = False
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: set[asyncio.Task] = set()

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

            # Launch task for cross-session concurrency
            task = asyncio.create_task(self._dispatch(msg))
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)

    async def stop(self) -> None:
        self._running = False
        # Wait for in-flight tasks
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process one inbound message with per-session locking."""
        key = msg.session_key

        # Per-session serial lock
        if key not in self._session_locks:
            self._session_locks[key] = asyncio.Lock()

        async with self._session_locks[key]:
            await self._process_message(msg)

    async def _process_message(self, msg: InboundMessage) -> None:
        """Core message processing: session -> history -> agent -> save -> respond."""
        try:
            # Check for /resume command before normal processing
            if msg.content.strip().startswith("/resume"):
                await self._handle_resume(msg)
                return

            # 1. Resolve session
            session = await resolve_session(
                session_key=msg.session_key,
                channel=msg.channel,
                chat_id=msg.chat_id,
                project_id=self._project_id,
                ttl_hours=self._session_ttl_hours,
            )

            # 2. Load history
            history = await get_session_history(
                session.conversation_id, self._max_history
            )

            # 3. Create agent and run
            response_text = await self._run_agent(history, msg.content)

            # 4. Save messages to conversation
            user_msg = {"role": "user", "content": msg.content}
            assistant_msg = {"role": "assistant", "content": response_text}
            await append_message(session.conversation_id, user_msg)
            await append_message(session.conversation_id, assistant_msg)

            # 5. Refresh session activity
            await refresh_session(msg.session_key, self._session_ttl_hours)

            # 6. Publish outbound
            await self._bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response_text,
                reply_to=msg.metadata.get("message_id"),
            ))

        except Exception:
            logger.exception("Gateway error processing message from %s", msg.session_key)
            # Send error response
            try:
                await self._bus.publish_outbound(OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Sorry, an error occurred while processing your message.",
                ))
            except Exception:
                logger.error("Failed to send error response", exc_info=True)

    async def _run_agent(self, history: list[dict], user_input: str) -> str:
        """Create agent, inject history, run to completion, extract output."""
        from src.agent.factory import create_agent
        from src.agent.loop import run_agent_to_completion
        from src.permissions.types import PermissionMode
        from src.tools.builtins.spawn_agent import extract_final_output

        state = await create_agent(
            role=self._role,
            task_description=user_input,
            project_id=self._project_id,
            run_id="",  # No workflow run for chat mode
            abort_signal=asyncio.Event(),
            permission_mode=PermissionMode.BYPASS,
        )

        # Inject history before the current user message
        # agent_factory already adds system prompt + current user message
        # We insert history between system prompt and the last user message
        if history and len(state.messages) >= 2:
            # messages[0] = system, messages[-1] = user (current)
            system_msg = state.messages[0]
            current_msg = state.messages[-1]
            state.messages = [system_msg] + history + [current_msg]
        elif history:
            state.messages = history + state.messages

        await run_agent_to_completion(state)
        output = extract_final_output(state.messages)
        return output or "(no response)"

    async def _handle_resume(self, msg: InboundMessage) -> None:
        """Handle /resume command: find paused pipelines, resume them.

        Syntax:
            /resume              — list paused runs for this project, auto-resume if only one
            /resume <run_id>     — resume a specific run
            /resume <run_id> <feedback>  — resume with feedback
        """
        from sqlalchemy import select

        from src.db import get_db
        from src.engine.pipeline import get_pipeline_status, resume_pipeline
        from src.engine.run import RunStatus
        from src.models import WorkflowRun

        parts = msg.content.strip().split(maxsplit=2)
        # parts[0] = "/resume", parts[1] = run_id (optional), parts[2] = feedback (optional)

        specified_run_id = parts[1] if len(parts) > 1 else None
        feedback = parts[2] if len(parts) > 2 else None

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
