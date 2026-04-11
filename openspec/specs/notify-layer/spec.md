# notify-layer Specification

## Purpose
TBD - created by archiving change add-notify-layer. Update Purpose after archive.
## Requirements
### Requirement: Notifier subscribes to EventBus and runs an independent consumer loop
The system SHALL provide a `Notifier` class in `src/notify/notifier.py`. On construction, `Notifier` SHALL call `bus.subscribe("notify", max_size=queue_size)` and store the returned queue. `Notifier.start()` SHALL launch a background `asyncio.Task` running `_loop` which drains the queue and processes events. `Notifier.stop(timeout_seconds)` SHALL cancel the loop and wait for it to finish, draining remaining queued events on best-effort basis.

#### Scenario: Notifier starts and consumes events
- **WHEN** `Notifier(bus=bus, channels=[...], rules=[...]).start()` is called and then `bus.emit(telemetry_event)` is called
- **THEN** `_loop` SHALL receive the event via its subscribed queue
- **AND** SHALL invoke each rule with the event

#### Scenario: Notifier stop cancels the loop
- **WHEN** `notifier.stop(timeout_seconds=5.0)` is called after `start`
- **THEN** the background task SHALL be cancelled or complete within the timeout
- **AND** subsequent `bus.emit` SHALL not raise (events simply accumulate in the queue unconsumed)

### Requirement: Rules are pure functions deriving Notification from TelemetryEvent
Each rule SHALL be a callable `Rule = Callable[[TelemetryEvent], Notification | None]`. A return of `None` means the rule did not match. Rules SHALL be stateless — they SHALL NOT query the database or access mutable module state. The module `src/notify/rules.py` SHALL export `default_rules() -> list[Rule]` returning the built-in rule set covering the 5 notification types: `run_started`, `run_completed`, `run_failed`, `human_review_needed`, `agent_progress`.

#### Scenario: run_failed rule matches pipeline_end with success=false
- **WHEN** a `PipelineEvent` with `pipeline_event_type="pipeline_end"` and payload containing `success=false` arrives
- **THEN** the `run_failed` rule SHALL return a `Notification(event_type="run_failed", user_id=..., payload={...})`

#### Scenario: run_completed rule matches pipeline_end with success=true
- **WHEN** a `PipelineEvent` with `pipeline_event_type="pipeline_end"` and payload containing `success=true` arrives
- **THEN** the `run_completed` rule SHALL return a `Notification(event_type="run_completed", ...)`

#### Scenario: Rule returns None when event does not match
- **WHEN** an `LLMCallEvent` is passed to the `run_failed` rule
- **THEN** the rule SHALL return `None`

#### Scenario: Rule exception does not poison the loop
- **WHEN** a rule raises `ValueError` while processing an event
- **THEN** the error SHALL be logged at WARNING level
- **AND** subsequent rules in the list SHALL still be evaluated
- **AND** subsequent events from the queue SHALL still be processed

### Requirement: Channel abstraction with name and async deliver
Every channel SHALL implement the `Channel` protocol: `name: str` attribute and `async def deliver(notification: Notification) -> None` method. Channels SHALL catch and log all exceptions inside `deliver` and SHALL NOT re-raise to the caller.

#### Scenario: Channel with failing deliver does not block others
- **WHEN** channel A's `deliver` raises and channel B's `deliver` succeeds for the same notification
- **THEN** channel B SHALL still deliver the notification
- **AND** a WARNING SHALL be logged naming channel A

### Requirement: SseChannel maintains per-user queues and delivers via fan-out
`SseChannel` SHALL maintain a mapping of `user_id -> list[asyncio.Queue]`. `register(user_id) -> asyncio.Queue` SHALL create a new queue and append it to the user's list. `unregister(user_id, queue) -> None` SHALL remove the queue from the user's list. `deliver(notification)` SHALL iterate the user's registered queues and call `put_nowait` on each, dropping oldest on full.

#### Scenario: Single user with one connection receives notification
- **WHEN** `queue = sse.register(user_id=1)` is called, then `sse.deliver(Notification(user_id=1, ...))` is called
- **THEN** the queue SHALL contain exactly one notification

#### Scenario: Single user with two connections receives notification on both
- **WHEN** two queues are registered for the same user_id and then `sse.deliver(notification)` is called
- **THEN** both queues SHALL receive the notification

#### Scenario: Notification for user with no active connection is dropped
- **WHEN** `sse.deliver(Notification(user_id=99, ...))` is called and `user_id=99` has no registered queues
- **THEN** `deliver` SHALL return normally
- **AND** no queue SHALL be modified

#### Scenario: Unregister removes queue
- **WHEN** `sse.register(1)` returns `q1`, then `sse.unregister(1, q1)` is called
- **THEN** subsequent `deliver(Notification(user_id=1, ...))` SHALL NOT put anything on `q1`

### Requirement: WechatChannel and DiscordChannel POST JSON via httpx
`WechatChannel(webhook_url)` and `DiscordChannel(webhook_url)` SHALL hold a shared `httpx.AsyncClient` with `timeout=10.0`. Their `deliver` methods SHALL build a channel-specific JSON body from the notification and POST to the configured webhook URL. On HTTP error, timeout, or network failure, the method SHALL log a WARNING with the host and status code (if available) and SHALL NOT re-raise.

#### Scenario: WeChat delivers successful notification
- **WHEN** `wechat.deliver(Notification(...))` is called and the webhook returns 200
- **THEN** the method SHALL return normally with no log warning

#### Scenario: Discord webhook 404 is logged, not raised
- **WHEN** `discord.deliver(Notification(...))` is called and the webhook returns 404
- **THEN** a WARNING SHALL be logged with the host and status code
- **AND** the method SHALL return normally without raising

#### Scenario: Webhook timeout is logged, not raised
- **WHEN** the HTTP POST to a webhook exceeds the 10-second timeout
- **THEN** the timeout exception SHALL be caught
- **AND** a WARNING SHALL be logged
- **AND** the method SHALL return normally

### Requirement: Notifier dispatches to channels based on user preferences
For each matched `Notification`, `Notifier._loop` SHALL load the user's channel preferences via `preferences.get(user_id, notification.event_type)` and SHALL iterate only the channels whose `name` appears in the returned list. A user with no preference entry SHALL default to empty, meaning no channels fire (opt-in model).

#### Scenario: User with sse+wechat preference receives via both channels
- **WHEN** `preferences.get(1, "run_failed")` returns `["sse", "wechat"]` and a matched notification arrives
- **THEN** both `SseChannel.deliver` and `WechatChannel.deliver` SHALL be called
- **AND** `DiscordChannel.deliver` SHALL NOT be called

#### Scenario: User with no preferences receives nothing
- **WHEN** `preferences.get(99, "run_failed")` returns `[]`
- **THEN** no channel `deliver` SHALL be called for user 99

### Requirement: user_notify_preferences table stores per-user per-event channel selection
The system SHALL add a PG table `user_notify_preferences(user_id INT NOT NULL, event_type TEXT NOT NULL, channels JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (user_id, event_type))`. An index on `(user_id)` SHALL support lookups. `preferences.get(user_id, event_type)` SHALL return the JSONB list (or empty list on miss). `preferences.set(user_id, event_type, channels)` SHALL upsert the row.

#### Scenario: Upsert replaces existing row
- **WHEN** `preferences.set(1, "run_failed", ["sse"])` is called and then `preferences.set(1, "run_failed", ["sse", "wechat"])` is called
- **THEN** `preferences.get(1, "run_failed")` SHALL return `["sse", "wechat"]`
- **AND** the table SHALL have exactly one row for `(1, "run_failed")`

#### Scenario: Missing entry returns empty list
- **WHEN** `preferences.get(999, "run_started")` is called and no row exists
- **THEN** the return value SHALL be `[]`

