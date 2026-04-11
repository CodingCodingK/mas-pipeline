## Context

Phase 6.1 introduced a per-session long-lived `SessionRunner` registry (`src/engine/session_registry.py`, `src/engine/session_runner.py`). REST `/api/sessions/*` endpoints go through it; `src/bus/gateway.py::_process_message` does not. The bus path still instantiates a one-shot agent via `_run_agent`, bypassing the registry entirely.

Reference implementation for the new path already exists at `src/api/sessions.py::send_message` (lines 153–176). The pattern is: `append_message` → `get_or_create_runner` → `runner.notify_new_message()`.

Relevant context docs:
- `.plan/rest_api_deployment_risks.md` — single-process assumptions for the registry
- `.plan/next_task.md` — scoping notes from Phase 6.1 archive
- Memory `decision_phase61_routing.md` — routing architecture A (long-lived runner + PG message stream)
- Nanobot `channels/base.py` + `channels/manager.py` — validation that "mandatory `send()`, optional `send_delta()`" is a legitimate baseline for external-chat platforms

## Goals / Non-Goals

**Goals:**

1. Eliminate the dual execution path: one `chat_session_id` → exactly one `SessionRunner` → exactly one `state.messages` list → deterministic message ordering.
2. Make bus-driven sessions observable through `GET /api/sessions/{id}/events` on the same terms as REST-driven sessions.
3. Preserve current bus UX: one user message → one assistant message per turn, delivered as a single outbound.
4. Keep the change surgical: gateway + one new test + update to existing regression test. Don't touch SessionRunner internals, REST API, or adapter interfaces.

**Non-Goals:**

1. **Streaming to bus adapters.** No `send_delta`, no typing indicators, no tool-progress hints. Deliberately skipped — see Decision 2.
2. **Per-channel message rendering abstraction.** No `render_progress` / `render_tool_call` hooks, no strategy pattern. Adapters stay at `BaseChannel.send(OutboundMessage)` as their only contract.
3. **Bus-side Last-Event-ID backfill.** Bus has no reconnect semantics; PG `Conversation.messages` is the source of truth for history. Decision 3.
4. **`/resume` command rewrite.** That path is pipeline-level (touches `resume_pipeline`), orthogonal to session turns.
5. **Multi-process runner registry.** Still single-process in this change; see `.plan/rest_api_deployment_risks.md` for the separate sticky-routing follow-up.

## Decisions

### Decision 1 — Subscribe-and-wait-for-`done`, don't poll PG

**Choice**: After waking the runner, `_process_message` attaches an `add_subscriber()` queue to the runner and awaits a `StreamEvent` of type `done`. On receipt, it reads the latest assistant message from `Conversation.messages` and publishes the outbound.

**Alternatives considered:**

- **Poll `get_messages()` in a loop until length grows.** Rejected: races against mid-turn writes (agent may append multiple assistant messages across tool calls), wastes DB queries, introduces latency jitter.
- **Block the gateway coroutine on a per-session `asyncio.Event` owned by the runner.** Rejected: requires changing `SessionRunner` internals, which the change scope explicitly forbids. The public `add_subscriber()` API already exists for this.
- **Use `runner.notify_new_message()` and return immediately (fire-and-forget).** Rejected: gateway must publish an outbound before the task ends; fire-and-forget has no hook for "reply ready".

**Why `done` specifically**: `src/streaming/events.py:75` — `done` is the single terminal event type already emitted by `agent_loop`. No new event type needed. If the runner exits without emitting `done` (crash, cancel), the idle-timeout fallback (Decision 4) catches it.

### Decision 2 — Non-streaming bus output (match nanobot's mandatory baseline)

**Choice**: Gateway buffers `StreamEvent`s silently and publishes exactly one `OutboundMessage` after `done`. No token deltas, no mid-turn edits, no tool progress forwarded to adapters.

**Alternatives considered:**

- **Forward `token_delta` events to adapters via a new `send_delta` method** (like nanobot does when `config.streaming=true`). Rejected for this change — would add a second method to `BaseChannel`, require per-channel rate limiting (Discord 5 edits/s), require WeChat 5s-webhook-window workaround, and widen the blast radius by 5×. Not a real user need today.
- **Render tool calls as inline progress text** ("🔧 reading file..."). Rejected — `send_tool_hints` config knob, rate limits, cancellation races. Premature.
- **Stream for Discord only, buffered for QQ/WeChat.** Rejected — branching behavior by channel is exactly the "minimum common denominator" trap. One path keeps behavior uniform across channels.

**Why this is safe to revisit later**: the proposal preserves `BaseChannel.send(OutboundMessage)` as the only contract. If we decide later to add streaming, the path is: add optional `send_delta()` on `BaseChannel` (default `pass`), flip a per-channel config flag, gateway checks `supports_streaming` before buffering. Nanobot has this exact pattern; we can lift it when needed.

### Decision 3 — No bus-side Last-Event-ID backfill

**Choice**: Bus adapters do not implement event-ID replay. If a bot restarts mid-turn, the in-flight turn is lost; the user's next message creates a new turn.

**Rationale**: Bus protocols don't have a reconnect concept — Discord/QQ/WeChat users don't "resubscribe". PG `Conversation.messages` holds committed state. Adding backfill would require per-adapter position tracking (Discord message_id, QQ seq, WeChat none) with near-zero user-visible benefit.

### Decision 4 — Subscriber lifecycle: `done` primary, 300s idle timeout fallback

**Choice:**

```python
runner = await get_or_create_runner(...)
queue = runner.add_subscriber()
try:
    runner.notify_new_message()
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=300)
        except asyncio.TimeoutError:
            logger.warning("Bus subscriber timeout on session %d", session.id)
            return  # give up, do not publish
        if event.type == "done":
            break
finally:
    runner.remove_subscriber(queue)
```

**Why both**: `done` covers 99% normal case. The 300s timeout is a deadman switch for crashed/stuck runners — matches CC's `idleTimeout.ts` pattern (env-var-driven grace period) and nanobot's retry bounds. Without it, a hung runner leaks a coroutine per hung turn.

**Why 300s (not configurable in this change)**: agent turns in production rarely exceed 60s; 300s gives 5× headroom. If real workloads prove this wrong, promote to `config.yaml` in a follow-up. Don't premature-optimize.

**Why no retry on timeout**: user on Discord/QQ/WeChat already waited 5 minutes; silent retry would double the wait. Log and drop is the least-bad behavior. Error response to the user is also an option but risks double-replying if the runner eventually emits `done` late. Ground rule: don't reply unless we're sure.

### Decision 5 — Remove `_session_locks` from `Gateway`

**Rationale**: `SessionRunner` already serializes turns per session (the runner's internal loop drains one message at a time). `Gateway._session_locks` becomes dead weight — worse, it creates a second serialization point that could deadlock with the runner's wakeup. Delete it.

**Concurrency model after this change:**

- Cross-session parallelism: the runner registry has one runner per session; they run in parallel.
- Intra-session ordering: `append_message` writes in arrival order to PG; the runner picks them up in that order via `notify_new_message()`.
- Gateway-side: `asyncio.create_task(self._dispatch(msg))` still fires per inbound, but `_dispatch` no longer holds a session-scoped lock.

### Decision 6 — `/resume` path unchanged

`_handle_resume` is pipeline-level (`resume_pipeline(pipeline_name, run_id, ...)`), not session-level. It has its own PG-backed state (`WorkflowRun.status == 'paused'`). Touching it would expand the change surface into Phase 5 territory for zero benefit.

## Risks / Trade-offs

1. **[Risk] Gateway would race against `SessionRunner._persist_new_messages` if it read the assistant text from PG on `done`.**
   → **Resolved during implementation**: Gateway now buffers `text_delta` events in memory and publishes the concatenated text when `done` arrives. No PG read happens for the assistant reply — the event stream is the source of truth for the current turn. The runner's post-turn persistence still runs for durability/history, but gateway doesn't depend on it. This required dropping the `_read_latest_assistant_message` helper from the original design.

2. **[Risk] 300s timeout fires on a legitimately long turn (e.g., deep research with many tool calls).**
   → Mitigation: 5 minutes is a lot for a chat turn. If observed in practice, bump the constant; ultimately promote to config. Not solving today.

3. **[Risk] Bus subscriber queue fills up mid-turn (default capacity 1024 events, see `session_runner.py:28`).**
   → Mitigation: runner already does oldest-drop on full (`_fanout` at line 146). Bus subscriber only cares about `done`, so dropped token events are harmless. `done` is near-end and small — unlikely to be dropped.

4. **[Risk] User sees no reply after 300s timeout.**
   → Trade-off accepted: silent drop > double-reply risk. Logged at WARNING.

5. **[Risk] Test flakiness from real runner async interleaving.**
   → Mitigation: new integration test uses the same PG + runner registry pattern as `test_rest_api_integration.py`; `agent_loop` mocked to emit `done` after user message is appended, deterministic ordering.

6. **[Risk] `_run_agent` deletion breaks anything else?**
   → Grep check in tasks phase. If nothing else imports it, delete cleanly.

7. **[Risk] Removing `_session_locks` surfaces a bug where the runner does NOT actually serialize.**
   → Mitigation: existing 20 test checks in `test_session_registry.py` cover this. Integration test for this change adds a second layer: two concurrent messages on same session → runner processes in order.

## Migration Plan

No data migration. Deploy as a code change:

1. Land the change on master.
2. Restart gateway/worker processes (single-process model — see `.plan/rest_api_deployment_risks.md`).
3. In-flight bus turns at restart: lost (same as today — the old inline `_run_agent` also dies on restart).
4. Rollback: revert commit, restart. No schema touched.

## Open Questions

1. Should the 300s timeout surface as a failed assistant message ("Sorry, that took too long — please try again") instead of silent drop? Leaning no (see Decision 4), but flagging for user confirmation during `/openspec-apply` review.
2. When we eventually enable streaming for Discord, do we want it to be a per-channel config flag (nanobot model) or a global setting? Out of scope for this change; noting for Phase 6.2 design.
