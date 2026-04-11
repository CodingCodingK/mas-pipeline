## Context

Change #1 (`refactor-extract-event-bus`) hoists telemetry's private queue into a shared `EventBus`. Telemetry is one consumer; this change adds the second consumer, `Notifier`, which turns observability events into user-facing pushes.

Two distinct delivery concerns:
1. **Frontend UI liveness**: a logged-in user watching the dashboard should see run/node state change in real time. Browser side uses `EventSource`, reconnects automatically, authenticates via `X-API-Key` header.
2. **External out-of-band push**: users who aren't watching should get a WeChat / Discord ping for important events (run failed, HITL review needed). These are HTTP POSTs from our server to their webhook URLs.

Both deliveries consume the **same** `Notification` data model; only the transport differs. Which channels fire for which event types is a per-user configuration.

## Goals / Non-Goals

**Goals:**
- Real-time delivery of 5 notification types (`run_started`, `run_completed`, `run_failed`, `human_review_needed`, `agent_progress`) to SSE / WeChat / Discord based on user preferences
- Zero business-code changes — Notifier derives events purely from telemetry signals on the bus
- Independent consumer lifecycle — Notifier failing never blocks telemetry or business code
- Per-user channel selection stored in PG, hot-editable via REST
- SSE endpoint reuses Phase 6.1's SSE auth + heartbeat patterns (consistent with session stream endpoint)
- Channel implementations are pluggable — adding email / Slack / PagerDuty later is O(single file)

**Non-Goals:**
- Notification history / read-receipts / mark-as-read UI — notifications are transient push events, not a persistent inbox
- Cross-process fan-out (multi-worker SSE) — single-worker deployment assumed; upgrade path is swapping SSE channel's in-memory queue for Redis pub/sub later
- Rich templating / localization — `Notification` carries a dict payload; channel formatters are minimal
- Mobile push (APNs / FCM), SMS, phone calls — out of scope
- Retry / persistence / DLQ for failed webhook POSTs — best-effort delivery with logged failures; reliability is upgrade work

## Decisions

### Decision 1: Rules are Python callables, not declarative YAML

**Choice:** `src/notify/rules.py` exports a list of `Rule = Callable[[TelemetryEvent], Notification | None]`. Each rule inspects one event type and returns either a constructed `Notification` or `None`. `default_rules()` returns the built-in set.

**Why:** 5 rules is small; a config-file DSL would be over-engineering. Callables are trivial to test, debug, and extend. When we eventually have 20+ rules, migrating to YAML is a straightforward refactor. Starting with code avoids premature abstraction.

**Alternatives considered:**
- YAML rules with jsonpath matchers: rejected as over-engineering for v1
- Decorator-based `@on_event("pipeline_end")` registration: rejected — would scatter rules across files, harder to audit
- Event-type → handler dict: rejected — a single telemetry event type may map to multiple notification types (e.g., `pipeline_end` → `run_completed` OR `run_failed` depending on payload)

### Decision 2: Rules fire on event type + payload, not on persisted DB state

**Choice:** Rules inspect the in-memory `TelemetryEvent` dataclass delivered via the bus. They do NOT query `telemetry_events` table or join against other tables.

**Why:** Latency. If a rule had to round-trip the DB to check "did this run previously emit a node_failed event?" the push would arrive seconds after the event. Keeping rules stateless on the event payload gives sub-100ms emit-to-channel latency. Any state that rules need must be pre-computed into the event payload by Phase 6.2's telemetry emission sites.

**Trade-off:** Some rules are naturally stateful (e.g., "alert if this is the 3rd failure in 5 minutes"). Those are deferred to a future "metrics alerting" consumer. Phase 6.3 sticks to stateless rules.

### Decision 3: One SSE queue per connected user, owned by `SseChannel`

**Choice:** `SseChannel` maintains `_queues: dict[user_id, list[asyncio.Queue]]`. Each time a browser connects to `/api/notify/stream`, the endpoint calls `sse_channel.register(user_id)` to get a fresh queue, then reads from it in the SSE loop. `Channel.deliver(notif)` iterates `_queues[notif.user_id]` and puts the notification on each (fan-out to multiple tabs / windows for the same user). On disconnect, endpoint calls `sse_channel.unregister(user_id, queue)`.

**Why:** Matches how the existing `/api/sessions/{id}/stream` SSE endpoint works in Phase 6.1 (per-subscriber in-memory queue), so reviewers see a consistent pattern. Supports multiple concurrent connections per user (multi-tab, phone + laptop). Upgrade path to Redis pub/sub: swap `list[asyncio.Queue]` with a Redis subscription per user — interface stays the same.

**Alternatives considered:**
- Single global queue with filtering by user_id in the endpoint: rejected — O(total_events) wakeups for every connected user is wasteful
- Per-user `asyncio.Event`: rejected — loses event payloads if consumer is slower than producer

### Decision 4: Webhook channels use httpx with a single shared `AsyncClient`

**Choice:** `WechatChannel` and `DiscordChannel` hold a single `httpx.AsyncClient` instance constructed at channel init, configured with `timeout=10s` and `limits=httpx.Limits(max_connections=20)`. Their `deliver` methods POST JSON and log (but do not re-raise) HTTP errors.

**Why:** Reusing the client avoids TCP/TLS handshake per event. `httpx` is already in the codebase. Failures MUST NOT propagate, otherwise a bad webhook URL would poison the `_loop` task and block all other deliveries.

**Trade-off:** No retry on transient failure. For v1, best-effort is acceptable — failed pushes are logged and lost. Retry with exponential backoff + DLQ is future work if users report missed notifications.

### Decision 5: Preferences are per-event-type, not per-rule

**Choice:** `user_notify_preferences` stores `(user_id, event_type, channels)` tuples where `event_type` is the **notification** event type (`run_failed`, `agent_progress`, etc.) and `channels` is a JSONB array of channel names (`["sse", "wechat"]`).

**Why:** Users think in terms of "tell me when a run fails", not "fire rule R7 which looks at pipeline_end with success=false". Decoupling rules from preferences lets us restructure the rule set without breaking users' saved choices.

### Decision 6: Notifier does NOT write to any persistent store

**Choice:** Notifier's `_loop` reads from bus queue → matches rules → calls `channel.deliver` → continues. No rows are written to PG during the hot path. The only PG interaction from `src/notify/*` is `preferences.py` doing CRUD on `user_notify_preferences`, triggered by REST handlers, not the loop.

**Why:** Phase 6.2's `telemetry_events` table is already the source-of-truth audit log. A "notifications_sent" table would duplicate that data and add write-path load. If we ever need a "notification log", it can be derived from telemetry via a query endpoint.

### Decision 7: SSE uses the same auth + heartbeat pattern as Phase 6.1's session stream

**Choice:** `/api/notify/stream` uses:
- `X-API-Key` header auth via existing `require_api_key` dependency
- `text/event-stream` with `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`
- 15-second heartbeat comment lines `:heartbeat\n\n`
- `event: <type>` + `data: <json>` format
- `Last-Event-ID` support for resume (but only for events still in the per-user queue — no DB backfill)

**Why:** Reviewers and operators already understand the Phase 6.1 pattern. Uniform patterns reduce cognitive load.

**Trade-off:** Events delivered before a client connects OR dropped due to queue overflow are not recoverable. This is consistent with Phase 6.1's session SSE behavior. If users need reliable delivery, they should configure a webhook channel (WeChat / Discord) in addition to SSE.

## Risks / Trade-offs

- **[Risk] Webhook URL in channel config may be wrong or rate-limited** → Mitigation: `deliver` catches all exceptions, logs with WARNING including URL host + status code, does not re-raise. Channel stays functional for future attempts.
- **[Risk] SSE client never disconnects cleanly, user's queue leaks** → Mitigation: endpoint uses `try/finally` to call `unregister`; also a periodic sweep (every 60s) removes queues that haven't been read from in 2 minutes.
- **[Risk] Rule function raises an exception on a malformed event** → Mitigation: `_loop` wraps each rule call in try/except, logs, continues with next rule; one bad rule does not poison the queue.
- **[Risk] Slow channel blocks other channels for the same notification** → Mitigation: `Notifier._loop` dispatches channels sequentially but each channel's `deliver` has a hard timeout (10s for webhooks, sync for SSE queue put). If users add many slow webhook channels, we revisit with concurrent dispatch using `asyncio.gather`.
- **[Risk] User preferences table missing for a user → AttributeError** → Mitigation: `preferences.get(user_id, event_type)` returns a default empty list; `Notifier` just drops the notification with a DEBUG log. Fresh users see no notifications until they opt in, which is the safe default.
- **[Risk] Bus drops a telemetry event under load → notification lost** → Mitigation: bus's drop-oldest + rate-limited warning is the same behavior telemetry has; losses are logged. For guaranteed delivery, future work would add a DB-backed "notify_outbox" pattern.
- **[Trade-off] No notification history UI** → Users can't see "what notifications fired last week". If needed, derive from telemetry via a query endpoint — cheaper than maintaining a separate store.
- **[Trade-off] Channel dispatch is sequential per notification** → For 3 channels it's fine. At 10+ channels per user, add `asyncio.gather`.

## Migration Plan

1. Change #1 (`refactor-extract-event-bus`) must be merged + archived first
2. Create the new `user_notify_preferences` table via `scripts/init_db.sql` update; existing deployments run the new DDL manually or via a migration script
3. Deploy the new `src/notify/` package + `main.py` wiring
4. Set `notify.enabled=true` in config; default channel prefs are empty per user (opt-in model)
5. Frontend work can begin wiring `EventSource('/api/notify/stream', ...)` immediately
6. Monitor logs for channel delivery failures; tune rules based on feedback

Rollback: set `notify.enabled=false` in config and restart — Notifier is not constructed, zero overhead on the bus (telemetry continues normally). Hard rollback: revert the commit.

## Open Questions

- Should `agent_progress` throttle at the Notifier layer? A long-running pipeline could emit dozens of progress events per minute. **Decision:** v1 fires every event; add throttling rule if observed as noisy.
- Should `human_review_needed` retry if no channel is configured? **Decision:** No — if user opted out of all channels for this event, they made that choice. Log once at DEBUG.
- WeChat enterprise webhook format vs. personal WeChat: **Decision:** v1 targets enterprise WeChat bot webhook format (`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...`). Personal WeChat is a separate protocol, not supported.
