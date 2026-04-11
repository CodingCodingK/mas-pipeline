## Why

Phase 6.1 shipped the `SessionRunner` registry for REST `/api/sessions/*` but left `src/bus/gateway.py::_process_message` on the old inline `_run_agent` path. A Discord/QQ/WeChat message and a REST message against the same `chat_session_id` therefore spawn **two parallel execution paths** — two `state.messages` lists, two agent loops, uncoordinated PG writes. This blocks Phase 6.2 (observability dashboard): the SSE stream at `GET /api/sessions/{id}/events` only sees REST-driven sessions, not bus-driven ones.

The fix is to route every bus message through `get_or_create_runner()` exactly like `src/api/sessions.py::send_message` already does, and have the bus dispatcher wait for the runner's `done` event before publishing the assistant reply. Explicit design decision (see `design.md`): **bus path is non-streaming** — we buffer until the turn ends and publish one final `OutboundMessage`, matching nanobot's mandatory `send()` baseline. Streaming stays REST-only.

## What Changes

- `src/bus/gateway.py::_process_message` rewritten to: resolve session → `append_message(user)` → `get_or_create_runner()` → `notify_new_message()` → subscribe to runner events → wait for `done` event → read latest assistant message from conversation → publish `OutboundMessage`.
- `Gateway._run_agent` removed (dead code once the rewrite lands).
- Per-session `asyncio.Lock` in `Gateway._session_locks` removed — the SessionRunner registry already serializes per session.
- Bus subscriber lifecycle: exit on `done` event; 300 s idle-timeout fallback for crashed runners (matches nanobot `send_max_retries` / CC `idleTimeout.ts` deadman-switch pattern).
- `/resume` command path in `_handle_resume` stays unchanged — it is pipeline-level, not session-level, and does not use SessionRunner.
- Integration test `scripts/test_bus_session_runner_integration.py` (new): post one bus message + one REST message against the same `chat_session_id`, assert single runner instance in registry and both messages appear in `Conversation.messages` in arrival order.
- `scripts/test_streaming_regression.py` 9.x: update to assert the new runner-based path (current tests exercise inline `_run_agent` which will be removed).
- **No new streaming protocol for bus adapters.** `BaseChannel.send(OutboundMessage)` remains the only contract bus gateway touches. Discord's edit-message / typing-indicator capabilities are intentionally not used in this change; revisit if/when a concrete product need appears.

## Capabilities

### New Capabilities
_(none)_

### Modified Capabilities
- `gateway-resume`: the bus message processing flow changes from inline agent execution to SessionRunner dispatch. Requirement-level: "Gateway SHALL run agent inline per message" → "Gateway SHALL delegate turn execution to the SessionRunner registry and wait for the `done` event before publishing outbound". `/resume` command behavior unchanged.
- `session-runner`: add requirement that external (non-HTTP) subscribers MAY attach via `add_subscriber()` and MUST detach via `remove_subscriber()` on `done` event or on a 300 s idle timeout, whichever comes first. No API changes, only an explicit contract for non-HTTP lifecycles.

## Impact

**Code**:
- `src/bus/gateway.py` — main rewrite (`_process_message` + removal of `_run_agent`, `_session_locks`).
- `scripts/test_streaming_regression.py` — section 9.x rewrite.
- `scripts/test_bus_session_runner_integration.py` — new file.

**Behavior**:
- Bus messages for a session with an already-running REST runner now queue behind that runner instead of racing it. Message ordering becomes deterministic per session.
- Bus response latency gains one runner-scheduling hop (~ms, negligible).
- Bus path does NOT gain streaming. Discord/QQ/WeChat users still see a single terminal message per turn. This is an explicit scope decision, not an oversight.

**Risks**:
- If a runner hangs without emitting `done`, bus subscriber waits 300 s before giving up. Logged, not retried.
- Bus message appears in `Conversation.messages` via `append_message` BEFORE the runner wakes — short window where a concurrent REST `GET /messages` could read the user message without the assistant reply. Acceptable; same as REST path today.

**No breakage**:
- REST `/api/sessions/*` untouched.
- SessionRunner / registry internals untouched.
- `/resume` bus command unchanged.
- Channel adapter interface (`BaseChannel.send`) unchanged.
