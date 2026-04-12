## Why

The backend has a complete session API (create session, send message, SSE event stream, message history) but no browser-based chat interface. Users cannot interact with agents through the web UI — they can only manage projects, agents, and pipelines. The chat page is the core interaction entry point that makes the system usable end-to-end.

## What Changes

- New `ChatPage` at `/projects/:id/chat/:sessionId` — full chat interface with message list, input box, and streaming AI responses
- New `ChatMessage` component — renders user messages (right-aligned), AI messages (left-aligned) with streaming text, thinking blocks (collapsible, gray italic), and tool call panels (collapsible, show name/arguments/output)
- New `ChatInput` component — text input with send button, Enter to send, Shift+Enter for newline, disabled while AI is responding
- New `ThinkingBlock` component — collapsible display of `thinking_delta` events
- New `ToolCallPanel` component — collapsible panel showing tool name, arguments, output, and success/failure status
- Modified `ChatPage` session creation flow — creates session via `POST /api/projects/{id}/sessions`, then subscribes to SSE stream via `GET /api/sessions/{id}/events`
- Modified `ProjectDetailPage` — adds "Chat" tab linking to chat page
- Modified `web/src/api/sse.ts` — support GET requests (currently hardcoded to POST)
- Modified `App.tsx` — add chat route

## Capabilities

### New Capabilities
- `chat-ui`: Browser-based chat interface with streaming message display, tool call visualization, and thinking process display

### Modified Capabilities
(none — all backend APIs are unchanged, only frontend additions)

## Impact

- **New files**: `ChatPage.tsx`, `ChatMessage.tsx`, `ChatInput.tsx`, `ToolCallPanel.tsx`, `ThinkingBlock.tsx`
- **Modified files**: `App.tsx` (route), `ProjectDetailPage.tsx` (tab), `sse.ts` (GET support)
- **No backend changes**
- **No new npm dependencies** — uses existing Tailwind CSS for styling
- **SSE event types consumed**: `text_delta`, `thinking_delta`, `tool_start`, `tool_end`, `tool_result`, `usage`, `done`, `error`
