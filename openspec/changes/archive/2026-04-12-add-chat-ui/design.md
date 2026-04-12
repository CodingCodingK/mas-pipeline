## Context

The web frontend (Phase 6.4) has 3 pages: ProjectsPage, ProjectDetailPage, RunDetailPage. The backend session API is complete: create session, send message, SSE event stream, message history. The SSE client (`web/src/api/sse.ts`) already handles SSE parsing with cross-chunk state. The chat UI is the missing link between these two layers.

SSE event types from `src/streaming/events.py`:
- `text_delta` → `{content}` — streaming AI text
- `thinking_delta` → `{content}` — AI thinking process
- `tool_start` → `{tool_call_id, name}` — tool call begins
- `tool_delta` → `{content}` — tool arguments streaming
- `tool_end` → `{tool_call_id, name, arguments}` — tool call complete
- `tool_result` → `{tool_call_id, output, success}` — tool execution result
- `usage` → `{input_tokens, output_tokens, thinking_tokens}` — token counts
- `done` → `{finish_reason}` — turn complete
- `error` → `{content}` — error message

## Goals / Non-Goals

**Goals:**
- User can chat with an agent in the browser with real-time streaming responses
- Tool calls are visible as collapsible panels showing name, arguments, and output
- Thinking process is visible as a collapsible block
- Messages persist across page reloads (via backend message history API)
- Auto-scroll to newest message during streaming

**Non-Goals:**
- Multi-user chat rooms or collaborative sessions
- File attachments in chat (covered by Change C: file upload UI)
- Chat history search
- Custom agent selection within chat (uses project's default pipeline agent)
- Markdown rendering of AI responses (plain text for MVP; can add later)

## Decisions

### D1: State management — React useState + useRef, no external state library

**Choice**: All chat state (messages, streaming status, SSE connection) managed with `useState` and `useRef` in ChatPage. No Redux, Zustand, or context providers.

**Rationale**: Single-page component with no cross-page state sharing. Adding a state library for one page is overengineering.

### D2: SSE connection lifecycle — connect on mount, reconnect on send

**Choice**: ChatPage subscribes to `GET /api/sessions/{id}/events` on mount. The SSE connection stays open for the session lifetime. If disconnected, reconnect when user sends next message. Use `AbortController` to clean up on unmount.

**Alternative**: Reconnect with `Last-Event-ID` for gap-free backfill. Deferred — the backend supports it but adds complexity for MVP.

### D3: Message data model — accumulator pattern for streaming

**Choice**: Maintain a `messages: ChatMessageData[]` array in state. Each entry has `role` ("user" | "assistant"), `content` (accumulated text), `thinking` (accumulated thinking text), and `toolCalls: ToolCallData[]`. During streaming, `text_delta` appends to the last assistant message's `content`; `tool_start`/`tool_end`/`tool_result` build up `toolCalls` entries matched by `tool_call_id`. On `done`, the message is finalized.

### D4: SSE client adaptation — add method parameter to fetchEventStream

**Choice**: Add optional `method` parameter to `fetchEventStream` (default `"GET"`). Session events use GET; pipeline events already use POST. Minimal change to existing code.

### D5: Chat session creation flow

**Choice**: When user navigates to `/projects/:id/chat`, auto-create a session via `POST /api/projects/{id}/sessions` with `mode: "chat"`, `channel: "web"`, `chat_id: <generated-uuid>`. Store session ID in URL as `/projects/:id/chat/:sessionId`. If sessionId is already in URL, load existing session and its message history.

### D6: Input behavior

**Choice**: `<textarea>` with Enter to send, Shift+Enter for newline. Disabled while AI is responding (between user send and `done` event). Auto-resize up to 4 lines.

## Risks / Trade-offs

- **[No markdown rendering]** → MVP shows AI text as plain text with `whitespace-pre-wrap`. Readable but not pretty for code blocks or lists. Can add a markdown renderer later.
- **[No reconnection with backfill]** → If SSE drops mid-stream, user must refresh. Acceptable for local/dev usage.
- **[Single session per visit]** → Each navigation to `/projects/:id/chat` creates a new session. No session picker or history sidebar. Can add later.
