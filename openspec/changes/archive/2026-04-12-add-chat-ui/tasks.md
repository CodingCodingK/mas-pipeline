## 1. SSE Client Adaptation

- [x] 1.1 Modify `web/src/api/sse.ts` — add optional `method` parameter to `fetchEventStream` (default `"GET"`), use it in the `fetch` call instead of hardcoded `"POST"`

## 2. Data Types

- [x] 2.1 Add chat-related TypeScript types to `web/src/api/types.ts` — `ChatSession`, `ChatMessageData` (role, content, thinking, toolCalls, isStreaming), `ToolCallData` (tool_call_id, name, arguments, output, success), `CreateSessionResponse`, `SendMessageResponse`

## 3. Components

- [x] 3.1 Create `web/src/components/ThinkingBlock.tsx` — collapsible block with gray italic text, collapsed by default, "Thinking..." header
- [x] 3.2 Create `web/src/components/ToolCallPanel.tsx` — collapsible panel showing tool name header, arguments and output when expanded, success/failure indicator
- [x] 3.3 Create `web/src/components/ChatMessage.tsx` — renders a single message: user (right-aligned, blue bg) or assistant (left-aligned, gray bg) with ThinkingBlock + text content + ToolCallPanels
- [x] 3.4 Create `web/src/components/ChatInput.tsx` — textarea with send button, Enter to send, Shift+Enter newline, disabled prop, auto-resize up to 4 lines

## 4. Chat Page

- [x] 4.1 Create `web/src/pages/ChatPage.tsx` — main chat page with session creation/loading, message history fetch, SSE subscription, message accumulator state, auto-scroll, send message handler

## 5. Routing and Navigation

- [x] 5.1 Update `web/src/App.tsx` — add routes `/projects/:id/chat` and `/projects/:id/chat/:sessionId`
- [x] 5.2 Update `web/src/pages/ProjectDetailPage.tsx` — add "Chat" tab that navigates to `/projects/:id/chat`

## 6. Validation

- [x] 6.1 TypeScript check — `npm run typecheck` passes
- [x] 6.2 Build check — `npm run build` succeeds
- [x] 6.3 Docker rebuild — `docker compose build web && docker compose up -d web` and verify chat page loads at `http://localhost/projects/1/chat`
