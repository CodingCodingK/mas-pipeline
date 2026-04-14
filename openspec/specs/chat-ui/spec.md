# chat-ui Specification

## Purpose
TBD - created by archiving change add-chat-ui. Update Purpose after archive.
## Requirements
### Requirement: Chat page routing and session creation
The app SHALL have a route `/projects/:id/chat` that auto-creates a new chat session and redirects to `/projects/:id/chat/:sessionId`. The route `/projects/:id/chat/:sessionId` SHALL load an existing session and display its message history.

#### Scenario: Navigate to chat creates new session
- **WHEN** user clicks "Chat" tab on ProjectDetailPage
- **THEN** the app calls `POST /api/projects/{id}/sessions` with `{mode: "chat", channel: "web", chat_id: <uuid>}`, receives a session ID, and navigates to `/projects/:id/chat/:sessionId`

#### Scenario: Direct link to existing session
- **WHEN** user navigates to `/projects/:id/chat/:sessionId` directly
- **THEN** the app loads existing message history via `GET /api/sessions/{sessionId}/messages` and displays all messages

### Requirement: SSE event stream subscription
The ChatPage SHALL subscribe to `GET /api/sessions/{sessionId}/events` on mount and process events in real time. The connection SHALL be cleaned up on unmount via AbortController.

#### Scenario: Receive streaming text
- **WHEN** the SSE stream emits `text_delta` events with `{content: "Hello"}, {content: " world"}`
- **THEN** the assistant message content accumulates to "Hello world" in real time

#### Scenario: Connection cleanup on unmount
- **WHEN** user navigates away from ChatPage
- **THEN** the SSE connection is aborted and no further events are processed

### Requirement: Message display
The ChatPage SHALL display messages in a scrollable list. User messages SHALL appear right-aligned with a distinct background color. Assistant messages SHALL appear left-aligned. The list SHALL auto-scroll to the bottom when new content arrives during streaming.

#### Scenario: User message appearance
- **WHEN** user sends a message "Hello"
- **THEN** the message appears right-aligned with user styling in the message list

#### Scenario: Assistant message streaming
- **WHEN** `text_delta` events arrive
- **THEN** the assistant message content updates in real time, displayed left-aligned

#### Scenario: Auto-scroll during streaming
- **WHEN** new text_delta events arrive and the user has not scrolled up
- **THEN** the message list automatically scrolls to show the latest content

### Requirement: Tool call visualization
Tool calls SHALL be displayed as collapsible panels within the assistant message. Each panel SHALL show the tool name as the header. When expanded, it SHALL show the tool arguments and execution output.

#### Scenario: Tool call starts
- **WHEN** a `tool_start` event with `{tool_call_id: "tc1", name: "read_file"}` arrives
- **THEN** a collapsed panel with header "read_file" appears in the current assistant message

#### Scenario: Tool call completes with result
- **WHEN** `tool_end` with `{tool_call_id: "tc1", name: "read_file", arguments: "{\"path\": \"/foo\"}"}` followed by `tool_result` with `{tool_call_id: "tc1", output: "file contents...", success: true}` arrives
- **THEN** expanding the "read_file" panel shows the arguments and output, with a success indicator

#### Scenario: Tool call fails
- **WHEN** `tool_result` arrives with `{success: false, output: "error message"}`
- **THEN** the panel shows a failure indicator and the error message

### Requirement: Thinking block display
Thinking content from `thinking_delta` events SHALL be displayed as a collapsible block (collapsed by default) with gray italic styling, before the assistant's main text content.

#### Scenario: Thinking content received
- **WHEN** `thinking_delta` events arrive with content
- **THEN** a collapsible "Thinking..." block appears, showing the accumulated thinking text when expanded

### Requirement: Chat input
The ChatPage SHALL have a text input area at the bottom with a send button. It SHALL support Enter to send and Shift+Enter for newline. The input SHALL be disabled while the assistant is responding.

#### Scenario: Send message
- **WHEN** user types "Hello" and presses Enter
- **THEN** the message is sent via `POST /api/sessions/{sessionId}/messages` with `{content: "Hello"}`, the input is cleared, and the message appears in the list

#### Scenario: Input disabled during response
- **WHEN** user sends a message and assistant is streaming a response
- **THEN** the input area and send button are disabled until a `done` event is received

#### Scenario: Multiline input
- **WHEN** user presses Shift+Enter
- **THEN** a newline is inserted in the input without sending the message

### Requirement: Project detail chat tab
The ProjectDetailPage SHALL include a "Chat" tab that navigates to the chat page for the current project.

#### Scenario: Chat tab navigation
- **WHEN** user clicks the "Chat" tab on ProjectDetailPage
- **THEN** the browser navigates to `/projects/:id/chat`

### Requirement: SSE client GET support
The `fetchEventStream` function in `web/src/api/sse.ts` SHALL accept an optional `method` parameter (default `"GET"`) to support both GET and POST SSE endpoints.

#### Scenario: GET SSE stream
- **WHEN** `fetchEventStream` is called with `method: "GET"` and no body
- **THEN** a GET request is made to the SSE endpoint with appropriate headers

#### Scenario: POST SSE stream (backward compatible)
- **WHEN** `fetchEventStream` is called with a body (existing usage)
- **THEN** behavior is unchanged — a POST request is made

### Requirement: Task notification card opens agent run detail drawer
When the chat UI renders a message whose `metadata.kind === "task_notification"`, the rendered card SHALL be clickable. Clicking the card SHALL open a shared `AgentRunDetailDrawer` component with `agentRunId` derived from `metadata.agent_run_id`. The drawer SHALL fetch `GET /api/agent-runs/{id}` and render:
- A header row with role, status, and three statistics badges (tool_use_count / total_tokens / duration_ms)
- The original task description
- The full message transcript (rendered read-only via the existing assistant-ui message renderer)
- The final result text

The main agent LLM context SHALL NOT be affected by drawer interactions; the drawer is pure frontend display.

#### Scenario: Click task_notification card
- **WHEN** a user clicks a task_notification card in the chat message list
- **THEN** `AgentRunDetailDrawer` SHALL open with the correct `agentRunId`
- **AND** the drawer SHALL issue a `GET /api/agent-runs/{id}` request
- **AND** upon response SHALL display the role/status/statistics/description/transcript/result

#### Scenario: Card shows statistics badges inline
- **WHEN** a task_notification card is rendered from a message whose `metadata` includes `tool_use_count`, `total_tokens`, `duration_ms`
- **THEN** the card SHALL render three small badges showing "N tools · K tokens · Xs" next to the role + status line
- **AND** the badges SHALL be rendered directly from metadata without re-parsing the XML body

#### Scenario: Drawer closes cleanly
- **WHEN** the user clicks outside the drawer, presses Escape, or clicks the close button
- **THEN** the drawer SHALL close and in-flight requests SHALL be aborted

