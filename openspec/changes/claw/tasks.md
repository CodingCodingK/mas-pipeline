## 1. MessageBus & Message Types

- [x] 1.1 Create `src/bus/__init__.py` module init
- [x] 1.2 Create `src/bus/message.py` — InboundMessage and OutboundMessage dataclasses with session_key property
- [x] 1.3 Create `src/bus/bus.py` — MessageBus class with inbound/outbound asyncio.Queue, publish/consume methods

## 2. ChatSession Model & DB

- [x] 2.1 Add `ChatSession` model to `src/models.py` (session_key unique, channel, chat_id, project_id, conversation_id, metadata, status, timestamps)
- [x] 2.2 Add chat_sessions table to `scripts/init_db.sql`

## 3. ChatSession CRUD & Redis Cache

- [x] 3.1 Create `src/bus/session.py` — resolve_session(): Redis lookup → PG fallback → create if not exists (auto-create Conversation)
- [x] 3.2 Implement refresh_session(): update last_active_at in PG + refresh Redis TTL
- [x] 3.3 Implement get_session_history(): load messages from Conversation, clean_orphan_messages, trim to max_messages

## 4. Channel Base & Manager

- [x] 4.1 Create `src/channels/__init__.py` module init
- [x] 4.2 Create `src/channels/base.py` — BaseChannel ABC (name, start, stop, send, _handle_message)
- [x] 4.3 Create `src/channels/manager.py` — ChannelManager: init channels from config, start_all, stop_all, dispatch_outbound

## 5. Discord Adapter

- [x] 5.1 Create `src/channels/discord.py` — DiscordChannel: WebSocket Gateway connection + heartbeat
- [x] 5.2 Implement Discord message receiving: MESSAGE_CREATE event parsing → _handle_message
- [x] 5.3 Implement Discord message sending: REST API POST with message splitting (2000 char limit)
- [x] 5.4 Implement Discord reconnection on WebSocket disconnect

## 6. QQ Adapter

- [x] 6.1 Create `src/channels/qq.py` — QQChannel: qq-botpy SDK integration
- [x] 6.2 Implement QQ event handlers: on_c2c_message_create + on_group_at_message_create
- [x] 6.3 Implement QQ message sending: post_c2c_message / post_group_message with chat_type cache
- [x] 6.4 Implement QQ message deduplication by message ID

## 7. WeChat Adapter

- [x] 7.1 Create `src/channels/wechat.py` — WeChatChannel: ilinkai HTTP long-poll connection
- [x] 7.2 Implement WeChat message receiving: poll getupdates → parse item_list → _handle_message
- [x] 7.3 Implement WeChat message sending: sendmessage with context_token cache + message splitting (4000 char)
- [x] 7.4 Implement WeChat token persistence: save/load state file for login survival across restarts

## 8. Gateway

- [x] 8.1 Create `src/bus/gateway.py` — Gateway class with run() main loop: consume_inbound → resolve_session → load history → agent_loop → save → publish_outbound
- [x] 8.2 Implement per-session serial processing with asyncio.Lock per session_key
- [x] 8.3 Implement cross-session concurrent processing via asyncio.create_task
- [x] 8.4 Implement error handling: per-message try/except, error OutboundMessage, loop continues

## 9. Config Integration

- [x] 9.1 Add ChannelsConfig to `src/project/config.py` — project_id, role, max_history, session_ttl_hours, per-channel sub-configs
- [x] 9.2 Support environment variable expansion in channel token/secret fields

## 10. CLI Entry Point

- [x] 10.1 Create gateway entry point — init DB/Redis, create MessageBus, start ChannelManager + Gateway concurrently
- [x] 10.2 Implement graceful shutdown on SIGINT/SIGTERM: stop channels → close connections

## 11. Tests

- [x] 11.1 Unit tests for InboundMessage / OutboundMessage (session_key, field access)
- [x] 11.2 Unit tests for MessageBus (publish/consume, FIFO order, blocking behavior)
- [x] 11.3 Unit tests for BaseChannel._handle_message (publishes InboundMessage to bus)
- [x] 11.4 Unit tests for ChannelManager (start/stop lifecycle, outbound dispatch routing, error tolerance)
- [x] 11.5 Unit tests for ChatSession CRUD + Redis cache (resolve_session: create/cache_hit/cache_miss, refresh, history loading)
- [x] 11.6 Unit tests for Gateway (end-to-end mock: inbound → session → agent → outbound, error handling, serial per-session)
- [x] 11.7 Unit tests for Discord adapter (mock WebSocket: receive MESSAGE_CREATE, send via REST, message splitting)
- [x] 11.8 Unit tests for QQ adapter (mock botpy: C2C + group events, dedup, send routing)
- [x] 11.9 Unit tests for WeChat adapter (mock httpx: long-poll receive, send with context_token, token persistence)

## 12. Docs

- [x] 12.1 Update `.plan/progress.md` — mark Phase 5.5 Claw complete
- [x] 12.2 Update `.plan/claw_design_notes.md` — add implementation details
