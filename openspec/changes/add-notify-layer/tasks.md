## 1. Schema and config

- [x] 1.1 Add `user_notify_preferences` table to `scripts/init_db.sql`: `(user_id INT NOT NULL, event_type TEXT NOT NULL, channels JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (user_id, event_type))` + index on `(user_id)` + FK to `users(id)`
- [x] 1.2 Add `NotifySettings` pydantic model to `src/project/config.py` with fields: `enabled: bool = True`, `wechat_webhook_url: str | None = None`, `discord_webhook_url: str | None = None`, `sse_queue_size: int = 500`, `sse_heartbeat_sec: int = 15`, `notify_queue_size: int = 5000`; wire into top-level `Settings` under `notify:` key

## 2. Notify core

- [x] 2.1 Create `src/notify/__init__.py` exporting `Notifier`, `NullNotifier`, `Notification`
- [x] 2.2 Create `src/notify/events.py` with `Notification` dataclass: `event_type: Literal[...]`, `user_id: int`, `title: str`, `body: str`, `payload: dict`, `notification_id: str`, `created_at: datetime`; include a `to_dict()` helper for channel serialization
- [x] 2.3 Create `src/notify/rules.py`:
  - Type alias `Rule = Callable[[TelemetryEvent], Notification | None]`
  - 5 built-in rules:
    - `rule_run_started` — matches `PipelineEvent(pipeline_event_type="pipeline_start")`
    - `rule_run_completed` — matches `PipelineEvent(pipeline_event_type="pipeline_end")` with payload `success=true`
    - `rule_run_failed` — matches `PipelineEvent(pipeline_event_type="pipeline_end")` with `success=false` OR `PipelineEvent(pipeline_event_type="node_failed")`
    - `rule_human_review_needed` — matches `PipelineEvent(pipeline_event_type="paused")` with payload reason indicating HITL
    - `rule_agent_progress` — matches `AgentTurnEvent` on turn completion (throttling not in v1)
  - `default_rules() -> list[Rule]` returns the 5 rules in declared order
  - Each rule resolves `user_id` from `project_id` via a passed-in async resolver (signature `async def resolve_user(project_id: int) -> int | None`) to avoid synchronous DB work in rule bodies — rules receive the pre-resolved user_id via a `context` argument, not by querying
  - Top-of-file doc comment explaining how to add a new rule
- [x] 2.4 Create `src/notify/preferences.py`:
  - `async def get(user_id: int, event_type: str, session_factory) -> list[str]` — returns JSONB channels list or `[]` on miss
  - `async def get_all(user_id: int, session_factory) -> dict[str, list[str]]` — returns full map for user
  - `async def set(user_id: int, event_type: str, channels: list[str], session_factory) -> None` — UPSERT via `ON CONFLICT (user_id, event_type) DO UPDATE`
- [x] 2.5 Create `src/notify/channels/__init__.py` exporting `Channel`, `SseChannel`, `WechatChannel`, `DiscordChannel`
- [x] 2.6 Create `src/notify/channels/base.py` — `Channel` Protocol: `name: str` attribute + `async deliver(notification: Notification) -> None`
- [x] 2.7 Create `src/notify/channels/sse.py`:
  - `SseChannel(name="sse")` with `_queues: dict[int, list[asyncio.Queue]]`
  - `register(user_id: int, max_size: int = 500) -> asyncio.Queue`
  - `unregister(user_id: int, queue: asyncio.Queue) -> None`
  - `async deliver(notification)` — for each queue in `_queues.get(notif.user_id, [])`, `put_nowait` with drop-oldest on full
  - `async cleanup_stale(idle_timeout_sec: float = 120)` — optional sweeper to drop queues untouched for too long
- [x] 2.8 Create `src/notify/channels/wechat.py`:
  - `WechatChannel(webhook_url, name="wechat")` holding `httpx.AsyncClient(timeout=10.0)`
  - `async deliver(notification)` — POST `{"msgtype": "markdown", "markdown": {"content": f"### {title}\n{body}"}}` to webhook; catch + log all failures
  - `async close()` to close the httpx client
- [x] 2.9 Create `src/notify/channels/discord.py`:
  - `DiscordChannel(webhook_url, name="discord")` holding `httpx.AsyncClient(timeout=10.0)`
  - `async deliver(notification)` — POST `{"content": f"**{title}**\n{body}", "username": "mas-pipeline"}` to webhook; catch + log all failures
  - `async close()` to close the httpx client
- [x] 2.10 Create `src/notify/notifier.py`:
  - `Notifier(bus, channels, rules, session_factory, queue_size)` constructor; subscribes to bus as `"notify"`
  - `start()` spawns `_loop` task
  - `_loop()` reads from `self._queue`, iterates rules, for each matched `Notification` loads user prefs and dispatches to enabled channels, catching per-rule and per-channel exceptions
  - `stop(timeout_seconds)` cancels the task and best-effort drains remaining events
  - `NullNotifier` as a subclass with no-op methods (parallel to `NullTelemetryCollector`)
  - Module-level `get_notifier()` / `set_notifier()` helpers

## 3. REST API

- [x] 3.1 Create `src/notify/api.py`:
  - `router = APIRouter(prefix="/notify", tags=["notify"])`
  - `GET /stream` — SSE endpoint using existing `require_api_key` dependency; resolve user_id; `register` queue; async generator loop emitting `event:`/`data:`/`id:` frames with heartbeat; `finally` unregisters
  - `GET /preferences` — returns `preferences.get_all(user_id)` as JSON dict
  - `PUT /preferences` — body `PreferenceUpdate(event_type: str, channels: list[str])`; validate `event_type` is one of the 5 known types and each channel name is in the configured list; call `preferences.set`; return fresh map
  - `GET /channels` — returns `[ch.name for ch in notifier.channels]`
- [x] 3.2 Modify `src/main.py`:
  - Import `Notifier`, `NullNotifier`, `SseChannel`, `WechatChannel`, `DiscordChannel`, notify router
  - In lifespan: after bus + telemetry are up, build channel list from settings (always `SseChannel`; add `WechatChannel` if `wechat_webhook_url` is set; add `DiscordChannel` if `discord_webhook_url` is set); construct `Notifier(bus=bus, channels=..., rules=default_rules(), session_factory=..., queue_size=settings.notify.notify_queue_size)` OR `NullNotifier()` when `notify.enabled=False`
  - `await notifier.start()`, store on `app.state.notifier`, `set_notifier(notifier)`
  - On shutdown: `await notifier.stop(timeout_seconds=5.0)` BEFORE `await collector.stop(...)` BEFORE `bus.close()`
  - Mount notify router under `/api/notify` alongside other routers

## 4. Unit tests

- [x] 4.1 Write `scripts/test_notify_rules.py`:
  - Each of the 5 rules: one matching event → returns Notification; one non-matching event → returns None
  - Rule exception path caught inside `Notifier._loop` is covered in test_notifier.py; this file just tests rule purity
- [x] 4.2 Write `scripts/test_notify_channels.py`:
  - `SseChannel.register` returns fresh queue; `deliver` fans out; `unregister` removes
  - `SseChannel.deliver` with no registered user is no-op
  - `SseChannel` drop-oldest when queue full
  - `WechatChannel.deliver` success path (mock httpx with `respx` or manual `AsyncMock` of `_client.post`)
  - `WechatChannel.deliver` 404 → logged, not raised
  - `DiscordChannel.deliver` success + failure paths
  - Mocked httpx timeouts → logged, not raised
- [x] 4.3 Write `scripts/test_notifier.py`:
  - Mocked bus + channels; call `notifier.start`, emit a telemetry event via a fake bus queue, assert matched channel's `deliver` was called
  - Rule raising exception → `_loop` catches, logs, continues with next rule
  - User with no preferences → no channel called
  - Multiple users with different prefs isolated
  - `stop` cancels the loop within timeout
- [x] 4.4 Write `scripts/test_notify_api.py` (FastAPI TestClient, mocked deps):
  - `GET /notify/stream` with valid key returns 200 and `text/event-stream` headers (use `stream=True` client or read a few frames)
  - `GET /notify/stream` without key → 401
  - `GET /notify/preferences` returns map
  - `PUT /notify/preferences` valid body → upsert + 200
  - `PUT /notify/preferences` invalid channel name → 400
  - `GET /notify/channels` → list of channel names

## 5. Integration tests (real PG + bus)

- [x] 5.1 Write `scripts/test_notify_integration.py`:
  - Construct real `EventBus` + `TelemetryCollector` + `Notifier` with `SseChannel` only (no webhook IO)
  - Seed `user_notify_preferences` row via direct SQL (`INSERT INTO users` + `INSERT INTO user_notify_preferences`)
  - Emit a `PipelineEvent(pipeline_event_type="pipeline_end", payload={"success": false, "user_id": 1})` via collector
  - Assert SSE channel's registered queue received a Notification with `event_type="run_failed"`
  - Disabled path: construct with `NullNotifier`, emit events, assert zero queue activity
  - Graceful-skip if PG not reachable (same pattern as telemetry integration tests)
- [x] 5.2 Write `scripts/test_notify_rest_integration.py`:
  - FastAPI TestClient + real PG
  - Seed user + preferences via SQL
  - `PUT /api/notify/preferences` to set prefs, `GET /api/notify/preferences` to verify
  - Open a short-lived SSE connection, emit a telemetry event via collector, read one frame from the stream, assert it matches
  - Graceful-skip if PG not reachable

## 6. Regression

- [x] 6.1 Run `scripts/test_event_bus.py` (change #1 tests) — must still pass
- [x] 6.2 Run full telemetry test surface (6 scripts) — must still pass
- [x] 6.3 Run `scripts/test_session_runner.py`, `scripts/test_streaming_regression.py`, `scripts/test_claw_gateway.py`, `scripts/test_bus_session_runner_integration.py` — must still pass
- [x] 6.4 Run `scripts/test_rest_api_integration.py`, `scripts/test_rest_api_auth.py`, `scripts/test_rest_api_sse_backfill.py` — notify router mount must not break existing routes

## 7. Validation and archive

- [x] 7.1 Run `openspec validate add-notify-layer --strict`
- [x] 7.2 Run the full notify test surface: `test_notify_rules.py`, `test_notify_channels.py`, `test_notifier.py`, `test_notify_api.py`, `test_notify_integration.py`, `test_notify_rest_integration.py`
- [x] 7.3 Run regression suite (task 6.1–6.4)
- [x] 7.4 Update `.plan/progress.md`: mark Phase 6.3 done, next step = Phase 6.4 (Web frontend)
- [x] 7.5 `git add` + commit
- [x] 7.6 Run `/openspec-archive-change add-notify-layer`
