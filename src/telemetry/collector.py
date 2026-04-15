"""Telemetry collector: contextvar linking, bounded queue, batched writer.

Architecture
------------
Emission sites call synchronous `record_*` methods. Each method appends a
`TelemetryEvent` to a bounded asyncio.Queue. A background `_writer_loop` task
drains the queue in batches and bulk-inserts rows into `telemetry_events`.

Linking
-------
Three module-level contextvars carry ambient IDs across async boundaries:
    - current_turn_id     — set by SessionRunner at turn entry
    - current_spawn_id    — set by spawn_agent just before creating the child task
    - current_run_id      — set by pipeline engine at pipeline_start

`record_*` methods automatically read these contextvars and merge them into the
event payload. Emission sites do not pass turn/spawn/run ids explicitly.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.events.bus import EventBus
from src.telemetry.events import (
    EVENT_TYPE_AGENT_SPAWN,
    EVENT_TYPE_AGENT_TURN,
    EVENT_TYPE_COMPACT,
    EVENT_TYPE_ERROR,
    EVENT_TYPE_HOOK,
    EVENT_TYPE_LLM_CALL,
    EVENT_TYPE_PIPELINE,
    EVENT_TYPE_SESSION,
    EVENT_TYPE_TOOL_CALL,
    TelemetryEvent,
)
from src.telemetry.pricing import PricingTable, load_pricing

logger = logging.getLogger(__name__)

# ── Contextvars ────────────────────────────────────────────────────────
# Module-level so every coroutine can read them. asyncio.create_task snapshots
# the current values at task creation — that is exactly the semantics we need
# for spawn_agent linking.

current_turn_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "telemetry_current_turn_id", default=None
)
current_spawn_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "telemetry_current_spawn_id", default=None
)
current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "telemetry_current_run_id", default=None
)
current_session_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "telemetry_current_session_id", default=None
)
current_project_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "telemetry_current_project_id", default=None
)


def _truncate(s: Any, length: int) -> str:
    if s is None:
        return ""
    txt = str(s) if not isinstance(s, str) else s
    return txt[:length]


def _hash_stack(exc: BaseException) -> str:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return hashlib.sha256(tb.encode("utf-8")).hexdigest()


def _serialise_args_preview(args: Any, length: int) -> str:
    try:
        if isinstance(args, (dict, list)):
            return _truncate(json.dumps(args, ensure_ascii=False, default=str), length)
        return _truncate(args, length)
    except Exception:
        return _truncate(repr(args), length)


class TelemetryCollector:
    """Real telemetry collector. Thread-safe enqueue, async batched writer."""

    def __init__(
        self,
        db_session_factory,
        bus: EventBus,
        *,
        enabled: bool = True,
        preview_length: int = 30,
        batch_size: int = 100,
        flush_interval_sec: float = 2.0,
        max_queue_size: int = 10000,
        pricing_table_path: str = "config/pricing.yaml",
    ) -> None:
        self._enabled = enabled
        self._preview_length = preview_length
        self._batch_size = batch_size
        self._flush_interval_sec = flush_interval_sec
        self._max_queue_size = max_queue_size
        self._pricing_table_path = pricing_table_path
        self._db_session_factory = db_session_factory
        self._bus = bus

        self._pricing = load_pricing(pricing_table_path)

        self._queue: asyncio.Queue[TelemetryEvent] = bus.subscribe(
            "telemetry", max_size=max_queue_size
        )
        self._writer_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

        self._turn_index: dict[int, int] = {}

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        if not self._enabled:
            logger.info("telemetry: disabled, skipping writer startup")
            return
        if self._writer_task is not None:
            return
        self._stopping.clear()
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name="telemetry-writer"
        )
        logger.info(
            "telemetry: started (batch=%d, flush=%.1fs, queue=%d)",
            self._batch_size, self._flush_interval_sec, self._max_queue_size,
        )

    async def stop(self, timeout_seconds: float = 10.0) -> None:
        if not self._enabled or self._writer_task is None:
            return
        self._stopping.set()
        try:
            await asyncio.wait_for(self._writer_task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            remaining = self._queue.qsize()
            logger.warning(
                "telemetry: graceful stop timed out with %d events still queued",
                remaining,
            )
            self._writer_task.cancel()
            try:
                await self._writer_task
            except (asyncio.CancelledError, Exception):
                pass
        self._writer_task = None

    # ── Pricing ────────────────────────────────────────────────────

    def reload_pricing(self) -> int:
        """Re-read pricing yaml and atomically swap the table. Returns model count."""
        new_table = load_pricing(self._pricing_table_path)
        self._pricing = new_table
        count = len(new_table.models)
        logger.info("telemetry: pricing reloaded — %d models", count)
        return count

    # ── Enqueue path ───────────────────────────────────────────────

    def _enqueue(self, event: TelemetryEvent) -> None:
        # Bus handles fan-out, drop-oldest overflow, and rate-limited warnings.
        self._bus.emit(event)

    # ── Public record_* API ────────────────────────────────────────

    def record_llm_call(
        self,
        *,
        provider: str,
        model: str,
        usage: Any,
        latency_ms: int,
        finish_reason: str,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> None:
        if not self._enabled:
            return
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cost = self._pricing.calculate_cost(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        )
        turn = current_turn_id.get()
        payload: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
            "cost_usd": cost,
            "turn_id": turn,
            "parent_turn_id": turn,
        }
        self._enqueue(self._envelope(EVENT_TYPE_LLM_CALL, payload))

    def record_tool_call(
        self,
        *,
        tool_name: str,
        args_preview: Any,
        duration_ms: int,
        success: bool,
        error_type: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "args_preview": _serialise_args_preview(args_preview, self._preview_length),
            "duration_ms": duration_ms,
            "success": success,
            "error_type": error_type,
            "error_msg": _truncate(error_msg, 500) if error_msg else None,
            "parent_turn_id": current_turn_id.get(),
        }
        self._enqueue(self._envelope(EVENT_TYPE_TOOL_CALL, payload))

    def record_agent_turn(
        self,
        *,
        turn_id: str,
        agent_role: str,
        started_at: datetime,
        ended_at: datetime,
        input_preview: str,
        output_preview: str,
        stop_reason: str,
        message_count_delta: int,
    ) -> None:
        if not self._enabled:
            return
        session_id = current_session_id.get()
        turn_index = 0
        if session_id is not None:
            turn_index = self._turn_index.get(session_id, 0) + 1
            self._turn_index[session_id] = turn_index

        payload: dict[str, Any] = {
            "turn_id": turn_id,
            "agent_role": agent_role,
            "turn_index": turn_index,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_ms": int((ended_at - started_at).total_seconds() * 1000),
            "message_count_delta": message_count_delta,
            "stop_reason": stop_reason,
            "input_preview": _truncate(input_preview, self._preview_length),
            "output_preview": _truncate(output_preview, self._preview_length),
            "spawned_by_spawn_id": current_spawn_id.get(),
        }
        env = self._envelope(EVENT_TYPE_AGENT_TURN, payload, agent_role=agent_role)
        self._enqueue(env)

    def record_agent_spawn(
        self,
        *,
        parent_role: str,
        child_role: str,
        task_preview: str,
        spawn_id: str,
    ) -> None:
        if not self._enabled:
            return
        payload: dict[str, Any] = {
            "spawn_id": spawn_id,
            "parent_role": parent_role,
            "child_role": child_role,
            "task_preview": _truncate(task_preview, self._preview_length),
            "parent_turn_id": current_turn_id.get(),
        }
        self._enqueue(self._envelope(EVENT_TYPE_AGENT_SPAWN, payload, agent_role=parent_role))

    def record_pipeline_event(
        self,
        *,
        pipeline_event_type: str,
        pipeline_name: str,
        node_name: str | None = None,
        duration_ms: int | None = None,
        error_msg: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        payload: dict[str, Any] = {
            "pipeline_event_type": pipeline_event_type,
            "pipeline_name": pipeline_name,
            "node_name": node_name,
            "duration_ms": duration_ms,
            "error_msg": _truncate(error_msg, 500) if error_msg else None,
            "turn_id": turn_id or current_turn_id.get(),
        }
        self._enqueue(self._envelope(EVENT_TYPE_PIPELINE, payload))

    def record_session_event(
        self,
        *,
        session_event_type: str,
        channel: str | None,
        mode: str,
        project_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        if not self._enabled:
            return
        payload: dict[str, Any] = {
            "session_event_type": session_event_type,
            "channel": channel,
            "mode": mode,
        }
        env = self._envelope(EVENT_TYPE_SESSION, payload)
        if project_id is not None:
            env.project_id = project_id
        if session_id is not None:
            env.session_id = session_id
        self._enqueue(env)

    def record_hook_event(
        self,
        *,
        hook_type: str,
        decision: str,
        latency_ms: int,
        rule_matched: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        payload: dict[str, Any] = {
            "hook_type": hook_type,
            "decision": decision,
            "latency_ms": latency_ms,
            "rule_matched": rule_matched,
            "parent_turn_id": current_turn_id.get(),
        }
        self._enqueue(self._envelope(EVENT_TYPE_HOOK, payload))

    def record_compact_event(
        self,
        *,
        trigger: str,  # "auto" | "reactive" | "micro"
        before_tokens: int,
        after_tokens: int,
        duration_ms: int,
        turn_index: int,
        agent_role: str | None = None,
    ) -> None:
        if not self._enabled:
            return
        ratio = (after_tokens / before_tokens) if before_tokens > 0 else 1.0
        payload: dict[str, Any] = {
            "trigger": trigger,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "ratio": round(ratio, 4),
            "duration_ms": duration_ms,
            "turn_index": turn_index,
            "parent_turn_id": current_turn_id.get(),
        }
        self._enqueue(
            self._envelope(EVENT_TYPE_COMPACT, payload, agent_role=agent_role)
        )

    def record_error(
        self,
        *,
        source: str,
        exc: BaseException | None = None,
        error_type: str | None = None,
        message: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if not self._enabled:
            return
        if exc is not None:
            error_type = error_type or type(exc).__name__
            message = message or str(exc)
            stacktrace_hash = _hash_stack(exc)
        else:
            stacktrace_hash = hashlib.sha256(
                f"{source}:{error_type}:{message}".encode()
            ).hexdigest()
        payload: dict[str, Any] = {
            "source": source,
            "error_type": error_type or "UnknownError",
            "message": _truncate(message, 500),
            "stacktrace_hash": stacktrace_hash,
            "context": context or {},
            "parent_turn_id": current_turn_id.get(),
        }
        self._enqueue(self._envelope(EVENT_TYPE_ERROR, payload))

    # ── Turn context manager ───────────────────────────────────────

    @asynccontextmanager
    async def turn_context(
        self,
        *,
        agent_role: str,
        input_preview: str,
        session_id: int | None = None,
        project_id: int | None = None,
    ):
        """Wrap an agent turn: set current_turn_id, emit agent_turn on exit.

        The caller pushes the final output text onto the yielded `capture` dict
        so we can record output_preview on exit:
            async with collector.turn_context(...) as capture:
                ... run agent ...
                capture['output'] = final_text
                capture['stop_reason'] = 'done'
                capture['message_count_delta'] = n
        """
        if not self._enabled:
            # Disabled path: still yield so callers can use the same control flow.
            yield {"output": "", "stop_reason": "done", "message_count_delta": 0}
            return

        turn_id = uuid.uuid4().hex
        token = current_turn_id.set(turn_id)
        started_at = datetime.now(timezone.utc)
        session_token = None
        project_token = None
        if session_id is not None:
            session_token = current_session_id.set(session_id)
        if project_id is not None:
            project_token = current_project_id.set(project_id)

        capture: dict[str, Any] = {
            "output": "",
            "stop_reason": "done",
            "message_count_delta": 0,
        }
        try:
            yield capture
        except BaseException as exc:
            capture["stop_reason"] = "error"
            self.record_agent_turn(
                turn_id=turn_id,
                agent_role=agent_role,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                input_preview=input_preview,
                output_preview=str(capture.get("output", "")),
                stop_reason=capture.get("stop_reason", "error"),
                message_count_delta=int(capture.get("message_count_delta", 0)),
            )
            self.record_error(source="session", exc=exc)
            current_turn_id.reset(token)
            if session_token is not None:
                current_session_id.reset(session_token)
            if project_token is not None:
                current_project_id.reset(project_token)
            raise
        else:
            self.record_agent_turn(
                turn_id=turn_id,
                agent_role=agent_role,
                started_at=started_at,
                ended_at=datetime.now(timezone.utc),
                input_preview=input_preview,
                output_preview=str(capture.get("output", "")),
                stop_reason=capture.get("stop_reason", "done"),
                message_count_delta=int(capture.get("message_count_delta", 0)),
            )
            current_turn_id.reset(token)
            if session_token is not None:
                current_session_id.reset(session_token)
            if project_token is not None:
                current_project_id.reset(project_token)

    # ── Envelope construction ──────────────────────────────────────

    def _envelope(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_role: str | None = None,
    ) -> TelemetryEvent:
        return TelemetryEvent(
            event_type=event_type,
            project_id=current_project_id.get() or 0,
            payload=payload,
            run_id=current_run_id.get(),
            session_id=current_session_id.get(),
            agent_role=agent_role,
        )

    # ── Writer loop ────────────────────────────────────────────────

    async def _writer_loop(self) -> None:
        while not self._stopping.is_set():
            batch = await self._collect_batch()
            if batch:
                await self._flush(batch)
        # Graceful drain on stop.
        while not self._queue.empty():
            batch = []
            while not self._queue.empty() and len(batch) < self._batch_size:
                batch.append(self._queue.get_nowait())
            if batch:
                await self._flush(batch)

    async def _collect_batch(self) -> list[TelemetryEvent]:
        batch: list[TelemetryEvent] = []
        deadline = time.monotonic() + self._flush_interval_sec
        while len(batch) < self._batch_size:
            if self._stopping.is_set():
                # Drain anything already queued without further waiting.
                while not self._queue.empty() and len(batch) < self._batch_size:
                    batch.append(self._queue.get_nowait())
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            batch.append(event)
        return batch

    async def _flush(self, batch: list[TelemetryEvent]) -> None:
        if not batch:
            return
        try:
            async with self._db_session_factory() as session:
                stmt = text(
                    "INSERT INTO telemetry_events "
                    "(ts, event_type, project_id, run_id, session_id, agent_role, payload) "
                    "VALUES (:ts, :event_type, :project_id, :run_id, :session_id, :agent_role, CAST(:payload AS JSONB))"
                )
                rows = [
                    {
                        "ts": e.ts,
                        "event_type": e.event_type,
                        "project_id": int(e.project_id or 0),
                        "run_id": e.run_id,
                        "session_id": e.session_id,
                        "agent_role": e.agent_role,
                        "payload": json.dumps(e.payload, ensure_ascii=False, default=str),
                    }
                    for e in batch
                ]
                await session.execute(stmt, rows)
                await session.commit()
        except Exception:
            logger.exception("telemetry: failed to flush %d events", len(batch))


class NullTelemetryCollector(TelemetryCollector):
    """Stand-in that never records or persists anything.

    Does NOT subscribe to the bus — a disabled collector should place zero
    load on event fan-out. The `bus` kwarg is accepted for signature
    compatibility and ignored.
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._enabled = False
        self._preview_length = 0
        self._batch_size = 0
        self._flush_interval_sec = 0.0
        self._max_queue_size = 0
        self._pricing_table_path = ""
        self._db_session_factory = None
        self._bus = bus  # retained but unused; we do not subscribe
        self._pricing = PricingTable()
        self._queue = asyncio.Queue(maxsize=1)
        self._writer_task = None
        self._stopping = asyncio.Event()
        self._turn_index = {}

    async def start(self) -> None:
        return None

    async def stop(self, timeout_seconds: float = 10.0) -> None:
        return None

    def reload_pricing(self) -> int:
        return 0


_global_collector: TelemetryCollector | None = None


def set_collector(collector: TelemetryCollector) -> None:
    global _global_collector
    _global_collector = collector


def get_collector() -> TelemetryCollector:
    """Return the process-global collector; fallback to NullTelemetryCollector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = NullTelemetryCollector()
    return _global_collector
