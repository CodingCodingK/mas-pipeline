## Why

mas-pipeline needs real-time notifications for two audiences: (1) the web frontend UI should auto-refresh when pipeline runs start/complete/fail or when a HITL review is pending; (2) external targets — enterprise WeChat, Discord bots, future email — should receive push notifications so users don't have to sit staring at a dashboard. Phase 6.2 landed telemetry; change #1 (`refactor-extract-event-bus`) extracts an `EventBus`. This change subscribes a new `Notifier` to the bus, derives user-facing notifications via rules, and delivers them to pluggable channels including a Server-Sent Events stream for the browser.

## What Changes

- Introduce `src/notify/` package with `notifier.py`, `rules.py`, `events.py`, `preferences.py`, `channels/{base,sse,wechat,discord}.py`, `api.py`
- `Notifier` subscribes to the shared `EventBus` under the name `"notify"`, runs a background `_loop` task that drains its queue, matches each telemetry event against a rule set, and dispatches matched `Notification` objects to enabled channels
- Define 5 rule types producing these notification event types (per original Phase 6.3 plan): `run_started`, `run_completed`, `run_failed`, `human_review_needed`, `agent_progress`
- Channel abstraction: `Channel.name`, `async Channel.deliver(notification)`. Three concrete implementations:
  - `SseChannel` — per-user in-memory `asyncio.Queue`s feeding `/api/notify/stream` SSE endpoint (replaces the original WebSocket plan)
  - `WechatChannel` — HTTP POST to enterprise WeChat webhook URL
  - `DiscordChannel` — HTTP POST to Discord webhook URL
- New PG table `user_notify_preferences(user_id, event_type, channels jsonb, updated_at)` — each user picks which channels to receive which events on; managed via REST CRUD
- SSE endpoint `GET /api/notify/stream` — authenticated via existing `X-API-Key`, reads the user's per-user SSE queue, emits `event: <type>\ndata: <json>` frames with heartbeat every 15s and `Last-Event-ID` support for reconnect
- Preferences REST: `GET /api/notify/preferences`, `PUT /api/notify/preferences`, `GET /api/notify/channels` (list available channels)
- Config: new `notify:` section in `Settings` — `enabled`, `wechat_webhook_url`, `discord_webhook_url`, `sse_queue_size`, `sse_heartbeat_sec`
- `src/main.py` lifespan wires `Notifier` alongside `TelemetryCollector` after the bus is constructed; mounts notify router under `/api/notify`

## Capabilities

### New Capabilities
- `notify-layer`: Real-time notification system — rule-based derivation from telemetry event stream, pluggable multi-channel delivery (SSE for UI, WeChat/Discord for external push), per-user per-event channel preferences
- `notify-rest-api`: HTTP + SSE interface — `/api/notify/stream` (SSE), `/api/notify/preferences` (CRUD), `/api/notify/channels` (discovery)

### Modified Capabilities
- (none) — this change is pure addition layered on top of the `event-bus` capability introduced in change #1

## Impact

- **New files**: `src/notify/__init__.py`, `src/notify/notifier.py`, `src/notify/events.py`, `src/notify/rules.py`, `src/notify/preferences.py`, `src/notify/channels/__init__.py`, `src/notify/channels/base.py`, `src/notify/channels/sse.py`, `src/notify/channels/wechat.py`, `src/notify/channels/discord.py`, `src/notify/api.py`, `scripts/test_notifier.py`, `scripts/test_notify_rules.py`, `scripts/test_notify_channels.py`, `scripts/test_notify_api.py`, `scripts/test_notify_integration.py`
- **Modified**: `src/main.py` (lifespan wiring + router mount), `src/project/config.py` (new `NotifySettings`), `scripts/init_db.sql` (new `user_notify_preferences` table + index)
- **Unchanged**: all Layer 1 emission sites, telemetry code (apart from the change #1 refactor that already landed), REST API auth, session runner, pipeline engine
- **DB schema**: 1 new table, 1 index — additive, no migration of existing rows
- **External API**: 3 new REST endpoints under `/api/notify/`
- **Dependencies**: `httpx` is already in the project (used by REST tests); no new packages
- **Regression risk**: low — Notifier is a brand new consumer of the bus. Telemetry + business code are untouched. Phase 6.2 tests + change #1 tests + existing REST tests are the regression gates.
