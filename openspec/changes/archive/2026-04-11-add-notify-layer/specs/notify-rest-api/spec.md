## ADDED Requirements

### Requirement: SSE endpoint streams notifications to authenticated user
The system SHALL expose `GET /api/notify/stream` returning `text/event-stream`. The endpoint SHALL require a valid `X-API-Key` via the existing `require_api_key` dependency. The handler SHALL resolve the caller's user_id from the API key, call `sse_channel.register(user_id)` to get a fresh queue, and enter a loop reading notifications from the queue and emitting `event: <event_type>\ndata: <json>\nid: <uuid>\n\n` frames. A heartbeat comment (`:heartbeat\n\n`) SHALL be sent every `sse_heartbeat_sec` seconds (default 15). On disconnect or exception, the handler SHALL call `sse_channel.unregister(user_id, queue)` in a `finally` block.

#### Scenario: Authenticated client receives events
- **WHEN** a client connects with a valid `X-API-Key` and a notification is delivered for their user_id
- **THEN** the client SHALL receive an SSE frame with `event: <type>` and `data: <json>`

#### Scenario: Missing API key returns 401
- **WHEN** a client connects without `X-API-Key`
- **THEN** the endpoint SHALL return HTTP 401

#### Scenario: Disconnect unregisters the queue
- **WHEN** the client closes the connection mid-stream
- **THEN** `sse_channel.unregister(user_id, queue)` SHALL be called
- **AND** the user's registered queue list SHALL no longer contain that queue

#### Scenario: Heartbeat keeps connection alive
- **WHEN** no notifications are delivered for `sse_heartbeat_sec` seconds
- **THEN** the endpoint SHALL send a `:heartbeat` comment line
- **AND** the client SHALL remain connected

### Requirement: Preferences CRUD via REST
The system SHALL expose:
- `GET /api/notify/preferences` — returns all preferences for the authenticated user as `{event_type: [channels]}` map
- `PUT /api/notify/preferences` — body `{event_type: str, channels: list[str]}` upserts a preference row; returns the updated map
- `GET /api/notify/channels` — returns the list of available channel names (from the Notifier's configured channel list), not user-scoped

All three endpoints SHALL require `X-API-Key` auth.

#### Scenario: Get preferences returns map
- **WHEN** the caller has two preference rows and sends `GET /api/notify/preferences` with a valid key
- **THEN** the response body SHALL be a JSON object mapping event_type to channel list for those two rows

#### Scenario: Put preferences upserts and returns fresh map
- **WHEN** `PUT /api/notify/preferences` is called with `{"event_type": "run_failed", "channels": ["sse", "wechat"]}`
- **THEN** the row SHALL be upserted in `user_notify_preferences`
- **AND** the response SHALL include `"run_failed": ["sse", "wechat"]` in the preferences map

#### Scenario: Put with unknown channel name is rejected
- **WHEN** `PUT /api/notify/preferences` includes a channel name not in the configured channel list
- **THEN** the response SHALL be HTTP 400 with an error message naming the invalid channel
- **AND** no row SHALL be written to the database

#### Scenario: Get channels returns configured list
- **WHEN** `GET /api/notify/channels` is called with a valid key and the Notifier is configured with `[SseChannel, WechatChannel, DiscordChannel]`
- **THEN** the response SHALL be `["sse", "wechat", "discord"]` (or similar, reflecting `channel.name` values)

### Requirement: notify router mounted under /api/notify
`src/main.py` SHALL import the notify router and mount it under `/api/notify` in the main API router group, alongside existing routers (sessions, projects, telemetry, admin).

#### Scenario: Router routes requests correctly
- **WHEN** a request arrives at `/api/notify/stream`
- **THEN** the SSE handler SHALL be invoked
- **AND** other routers (e.g., `/api/telemetry/runs/...`) SHALL continue to work without interference
