## ADDED Requirements

### Requirement: Bus messages dispatch through SessionRunner registry
For every `InboundMessage` consumed from the message bus that is NOT a `/resume` command, Gateway SHALL delegate turn execution to the SessionRunner registry instead of running `agent_loop` inline. The dispatch flow SHALL be:

1. Resolve `ChatSession` via `resolve_session(session_key, channel, chat_id, project_id, ttl_hours)`.
2. Append the user message to the conversation via `append_message(conversation_id, {"role": "user", "content": msg.content})`.
3. Acquire a runner via `get_or_create_runner(session_id, mode, project_id, conversation_id)`.
4. Attach a subscriber queue via `runner.add_subscriber()`.
5. Call `runner.notify_new_message()` to wake the runner.
6. Accumulate `text_delta` events from the subscriber queue until a terminal `done` event arrives (see subscriber lifecycle requirement below).
7. Publish the concatenated text as a single `OutboundMessage` via `bus.publish_outbound(...)`. If no `text_delta` events were received, publish the placeholder `"(no response)"` instead.
8. Detach the subscriber via `runner.remove_subscriber(queue)` in a `finally` block.
9. Refresh session activity via `refresh_session(session_key, ttl_hours)`.

Gateway SHALL NOT instantiate an agent directly via `create_agent` + `run_agent_to_completion` for bus messages. Gateway SHALL NOT read assistant text from `Conversation.messages` — the event stream is the source of truth for the current turn to avoid racing against `SessionRunner._persist_new_messages`, which runs only after `done` has already been fanned out.

#### Scenario: Bus and REST share one runner for the same chat_session_id
- **WHEN** a bus message arrives for `session_key=X` while a REST `SessionRunner` already exists for the same `chat_session_id`
- **THEN** Gateway SHALL obtain the existing runner via `get_or_create_runner` (no new runner created)
- **AND** the user message SHALL appear in the same `Conversation.messages` list observed by `GET /api/sessions/{id}/events`
- **AND** the registry SHALL contain exactly one SessionRunner for that session id

#### Scenario: First bus message on a new session creates a runner
- **WHEN** a bus message arrives for a session_key with no existing runner in the registry
- **THEN** `get_or_create_runner` SHALL create a fresh SessionRunner
- **AND** the runner SHALL process the user message and emit a `done` event
- **AND** Gateway SHALL publish one outbound message containing the assistant reply

#### Scenario: Two bus messages on the same session serialize through runner
- **WHEN** two bus messages arrive for the same session_key within the same second
- **THEN** both SHALL be appended to `Conversation.messages` in arrival order via `append_message`
- **AND** the runner SHALL process them sequentially (not in parallel)
- **AND** Gateway SHALL publish two outbound messages, one per turn, in order

#### Scenario: Inline _run_agent path is not invoked
- **WHEN** any non-`/resume` bus message is dispatched
- **THEN** `Gateway._run_agent` SHALL NOT be called (the method is removed from the class)
- **AND** `src.agent.factory.create_agent` SHALL NOT be called by Gateway code

### Requirement: Bus path is non-streaming (one outbound per turn)
Gateway SHALL buffer `text_delta` content received from the runner and publish exactly one `OutboundMessage` per turn, only after the `done` event arrives. Gateway SHALL NOT forward `text_delta`, `thinking_delta`, `tool_start`, `tool_delta`, `tool_end`, `tool_result`, or `usage` events to bus adapters as intermediate messages. Non-`text_delta` events SHALL be silently dropped (buffer only receives text). Channel adapters SHALL continue to implement only `BaseChannel.send(OutboundMessage)`; no `send_delta` method is added in this change.

#### Scenario: Text deltas are silently buffered
- **WHEN** the runner emits 50 `text_delta` events during a turn
- **THEN** Gateway SHALL NOT publish any intermediate `OutboundMessage`
- **AND** upon receiving `done`, Gateway SHALL publish exactly one `OutboundMessage` whose content is the concatenation of all `text_delta.content` values, with leading/trailing whitespace stripped

#### Scenario: Tool progress is not leaked to channel
- **WHEN** the runner emits `tool_start`, `tool_delta`, `tool_end`, `tool_result`, or `usage` events during a turn
- **THEN** Gateway SHALL NOT render tool hints into any outbound message
- **AND** these events SHALL NOT contribute to the text buffer
- **AND** the channel user SHALL see a single final reply with no tool metadata

#### Scenario: Turn with no text content falls back to placeholder
- **WHEN** a turn ends with `done` but produced zero `text_delta` events
- **THEN** Gateway SHALL publish an `OutboundMessage` with content `"(no response)"`

### Requirement: Bus subscriber lifecycle — done primary, 300s idle timeout fallback
While awaiting events from a SessionRunner subscriber queue, Gateway SHALL apply a per-event timeout of 300 seconds via `asyncio.wait_for`. If the timeout fires before a `done` event is received, Gateway SHALL log a WARNING, detach the subscriber, and return WITHOUT publishing any outbound. Gateway SHALL NOT retry the turn.

Subscriber detachment SHALL always occur in a `finally` block to guarantee cleanup on exception, timeout, or normal completion.

#### Scenario: Normal turn completes via done event
- **WHEN** the runner emits events and then a terminal `done` event within 300 seconds
- **THEN** Gateway SHALL detach its subscriber and publish one outbound
- **AND** no WARNING SHALL be logged

#### Scenario: Stuck runner triggers timeout
- **WHEN** the runner does not emit `done` within 300 seconds of wakeup
- **THEN** Gateway SHALL log "Bus subscriber timeout on session {id}" at WARNING
- **AND** the subscriber queue SHALL be removed via `remove_subscriber`
- **AND** no `OutboundMessage` SHALL be published for that turn
- **AND** no retry SHALL occur

#### Scenario: Subscriber detached on exception
- **WHEN** Gateway raises an unexpected exception mid-turn while awaiting events
- **THEN** the `finally` block SHALL call `remove_subscriber(queue)`
- **AND** the runner's subscriber set SHALL NOT retain the dead queue

### Requirement: Gateway SHALL NOT hold a per-session asyncio lock
Gateway SHALL rely on SessionRunner's intrinsic per-session serialization (one runner per session, one turn at a time) and SHALL NOT maintain its own `_session_locks` dict. Cross-session parallelism SHALL be preserved via `asyncio.create_task` per inbound message.

#### Scenario: No gateway-level lock contention
- **WHEN** bus messages for session A and session B arrive concurrently
- **THEN** both dispatch tasks SHALL execute in parallel (no shared gateway lock)
- **AND** session A and session B SHALL run on independent SessionRunner instances

#### Scenario: Same-session messages serialize inside the runner, not the gateway
- **WHEN** two bus messages for session A arrive concurrently
- **THEN** Gateway SHALL append both to `Conversation.messages` without acquiring any gateway-owned lock
- **AND** the SessionRunner's main loop SHALL process them one at a time

### Requirement: /resume command path remains pipeline-level and unchanged
Messages matching the `/resume` command SHALL continue to be handled by `Gateway._handle_resume` exactly as today: they invoke `resume_pipeline(pipeline_name, run_id, feedback)` directly, do NOT go through the SessionRunner registry, and do NOT append messages to `Conversation.messages`.

#### Scenario: /resume bypasses runner
- **WHEN** a bus message with content `/resume run-abc` arrives
- **THEN** Gateway SHALL dispatch it to `_handle_resume`
- **AND** `get_or_create_runner` SHALL NOT be called for this message
- **AND** `append_message` SHALL NOT be called for this message

#### Scenario: Regular chat message does not enter resume path
- **WHEN** a bus message with content "please resume the task" arrives
- **THEN** Gateway SHALL route it through the SessionRunner dispatch flow, not `_handle_resume`
