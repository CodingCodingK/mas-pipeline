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

import yaml

from src.bus.message import Attachment, OutboundMessage
from src.engine.run import (
    get_run,
    subscribe_pipeline_events,
    unsubscribe_pipeline_events,
)

if TYPE_CHECKING:
    from src.bus.bus import MessageBus

logger = logging.getLogger(__name__)

# Discord free-tier attachment ceiling. Keep a small safety margin under
# the hard 10MB so multipart overhead never tips us over.
_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


def _read_agent_description(path) -> str:
    """Read the `description` field from an agent md file's YAML frontmatter.

    Each call hits the disk fresh — no cache. Pause notifications are rare
    and agents/*.md is bind-mounted so dev edits go live without a restart.
    Returns '' on any error (missing file, no frontmatter, no description).
    """
    try:
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") else open(path, encoding="utf-8").read()
    except Exception:
        return ""
    if not text.startswith("---"):
        return ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        return ""
    desc = fm.get("description") if isinstance(fm, dict) else None
    return desc if isinstance(desc, str) else ""


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
                attachments: list[Attachment] = []
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
                elif etype == "pipeline_paused":
                    paused_at = event.get("paused_at", "?")
                    text, attachments = await self._build_paused_message(paused_at)
                elif etype == "pipeline_end":
                    status = event.get("status", "completed")
                    err = event.get("error")
                    if status == "failed" or err:
                        text = f"[run #{self.run_id}] failed" + (
                            f": {str(err)[:500]}" if err else ""
                        )
                    else:
                        text, attachments = await self._build_done_message(status)
                    terminal = True

                if text:
                    await self._publish(text, attachments)

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

    async def _build_done_message(
        self, status: str
    ) -> tuple[str, list[Attachment]]:
        """Fetch the finished run and render the completion message + md attachment.

        Falls back to a plain-text summary + web-UI download hint when the
        final output exceeds Discord's attachment ceiling.
        """
        # Import here to avoid a circular at module import time.
        from src.api.runs import build_run_markdown

        try:
            run = await get_run(self.run_id)
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: get_run failed", self.run_id
            )
            run = None

        if run is None:
            return f"[run #{self.run_id}] {status}", []

        try:
            base_name, body = build_run_markdown(run, include_all=False)
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: build_run_markdown failed", self.run_id
            )
            return f"[run #{self.run_id}] {status}", []

        body_bytes = body.encode("utf-8")
        if len(body_bytes) > _MAX_ATTACHMENT_BYTES:
            size_kb = len(body_bytes) // 1024
            text = (
                f"[run #{self.run_id}] {status} — 输出 {size_kb}KB 过大，"
                f"请在 Web UI 下载：/api/runs/{self.run_id}/export?fmt=md"
            )
            return text, []

        attachment = Attachment(
            filename=f"{base_name}.md",
            content_bytes=body_bytes,
            mime="text/markdown; charset=utf-8",
        )
        text = f"[run #{self.run_id}] {status} — 结果见附件"
        return text, [attachment]

    async def _build_paused_message(
        self, paused_node: str
    ) -> tuple[str, list[Attachment]]:
        """Render a pipeline_paused notification with attachment + human text.

        Pulls:
          - paused_output from workflow_runs.metadata_ (what needs review)
          - pipeline YAML (to know node order + the next downstream role)
          - agents/{role}.md frontmatter description (for human text)

        No cache — files are re-read each time. Pause events are rare
        enough that the overhead is irrelevant, and dev edits to agent
        files go live immediately without a gateway restart.
        """
        # Imports inside to dodge module-load circularity with src.api.runs.
        from src.api.runs import build_paused_markdown
        from src.engine.pipeline import load_pipeline
        from src.storage.layered import resolve_agent_file, resolve_pipeline_file

        base_text = (
            f"[run #{self.run_id}] paused at `{paused_node}` — 请审阅。\n"
            f"approve → `/resume {self.run_id} approve`\n"
            f"打回 → `/resume {self.run_id} reject:<理由>`"
        )

        try:
            run = await get_run(self.run_id)
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: get_run failed on pause", self.run_id
            )
            return base_text, []
        if run is None:
            return base_text, []

        # Resolve pipeline YAML + find the paused node's output field and the
        # next downstream node. Everything here is best-effort — if any step
        # fails we still emit the minimal pause notification so the user isn't
        # left stranded.
        paused_def = None
        output_name = paused_node
        next_node_name: str | None = None
        next_role: str | None = None
        paused_role: str | None = None
        pipeline_desc = ""
        try:
            yaml_path = resolve_pipeline_file(run.pipeline, run.project_id)
            pipeline_def = load_pipeline(str(yaml_path))
            pipeline_desc = pipeline_def.description or ""
            for i, node in enumerate(pipeline_def.nodes):
                if node.name == paused_node:
                    paused_def = node
                    paused_role = node.role
                    output_name = node.output or paused_node
                    if i + 1 < len(pipeline_def.nodes):
                        nxt = pipeline_def.nodes[i + 1]
                        next_node_name = nxt.name
                        next_role = nxt.role
                    break
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: pipeline lookup failed", self.run_id
            )

        # Human description — read agents/{role}.md frontmatter each call.
        role_desc = ""
        if paused_role:
            try:
                agent_path = resolve_agent_file(paused_role, run.project_id)
                role_desc = _read_agent_description(agent_path) or ""
            except Exception:
                logger.exception(
                    "ChatProgressReporter %s: agent frontmatter read failed",
                    self.run_id,
                )

        # Compose the human-friendly body (3-5 lines, dense).
        lines = [f"[run #{self.run_id}] paused at `{paused_node}` — 请审阅「{output_name}」。"]
        if next_node_name and next_role:
            lines.append(f"下一步：`{next_node_name}` ({next_role}) 将基于你的审阅结果继续。")
        elif paused_def is not None:
            lines.append("下一步：这是 pipeline 最后一个节点，approve 即完成。")
        if role_desc:
            lines.append(f"节点职责：{role_desc[:200]}")
        if pipeline_desc:
            lines.append(f"(pipeline: {pipeline_desc[:120]})")
        lines.append("")
        lines.append(f"approve → `/resume {self.run_id} approve`")
        lines.append(f"打回 → `/resume {self.run_id} reject:<理由>`")
        text = "\n".join(lines)

        # Attach the paused_output as .md — falls back to inline hint if too big.
        try:
            base_name, body = build_paused_markdown(run, paused_node)
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: build_paused_markdown failed",
                self.run_id,
            )
            return text, []

        body_bytes = body.encode("utf-8")
        if len(body_bytes) > _MAX_ATTACHMENT_BYTES:
            size_kb = len(body_bytes) // 1024
            text += (
                f"\n\n⚠️ 待审阅内容 {size_kb}KB 过大，"
                f"请在 Web UI 查看：/projects/{run.project_id}/runs/{self.run_id}"
            )
            return text, []

        attachment = Attachment(
            filename=f"{base_name}.md",
            content_bytes=body_bytes,
            mime="text/markdown; charset=utf-8",
        )
        return text, [attachment]

    async def _publish(
        self, text: str, attachments: list[Attachment] | None = None
    ) -> None:
        """Double-write: outbound queue + conversation history."""
        try:
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel=self.channel,
                    chat_id=self.chat_id,
                    content=text,
                    attachments=attachments or [],
                )
            )
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: publish_outbound failed", self.run_id
            )

        try:
            from src.session.manager import append_message

            meta: dict = {
                "source": "progress_reporter",
                "run_id": self.run_id,
            }
            if attachments:
                meta["attachments"] = [
                    {"filename": a.filename, "size": len(a.content_bytes)}
                    for a in attachments
                ]
            await append_message(
                self.conversation_id,
                {
                    "role": "assistant",
                    "content": text,
                    "metadata": meta,
                },
            )
        except Exception:
            logger.exception(
                "ChatProgressReporter %s: append_message failed", self.run_id
            )
