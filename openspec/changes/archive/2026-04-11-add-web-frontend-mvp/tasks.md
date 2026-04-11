## 1. Scaffolding

- [x] 1.1 Create `web/package.json` with pinned deps: react 18, react-dom 18, react-router-dom 6, typescript 5, vite 5, @vitejs/plugin-react 4, tailwindcss 3, postcss, autoprefixer, vitest 1, @types/react, @types/react-dom
- [x] 1.2 Create `web/tsconfig.json` + `web/tsconfig.node.json` (strict mode, `jsx: react-jsx`, path alias `@/*` → `src/*`)
- [x] 1.3 Create `web/vite.config.ts` — React plugin, vitest environment `node` (no jsdom), resolve alias `@` → `src`
- [x] 1.4 Create `web/tailwind.config.js` + `web/postcss.config.js`
- [x] 1.5 Create `web/index.html` — single `<div id="root">` + `type="module"` script tag
- [x] 1.6 Create `web/.gitignore` — ignore `node_modules`, `dist`, `.env.local`
- [x] 1.7 Create `web/.env.example` — `VITE_API_BASE=http://localhost:8000/api`, `VITE_API_KEY=`
- [x] 1.8 Run `npm install` inside `web/` and commit `package-lock.json`

## 2. Core plumbing

- [x] 2.1 `web/src/main.tsx` — render `<App />` into `#root`, wrap in `<BrowserRouter>`
- [x] 2.2 `web/src/index.css` — Tailwind base/components/utilities imports only
- [x] 2.3 `web/src/api/types.ts` — TS interfaces mirroring Pydantic models:
  - `ProjectOut`, `ProjectList`
  - `AgentItem`, `AgentListResponse`, `AgentReadResponse`
  - `PipelineItem`, `PipelineListResponse`, `PipelineReadResponse`
  - `RunDetail`, `TriggerRunResponse`
  - `ApiErrorBody` (`detail: string | {detail: string; references: {project_id: number|null; pipeline: string; role: string}[]}`)
- [x] 2.4 `web/src/api/client.ts`:
  - `ApiError extends Error { status; body }`
  - `request<T>(method, path, body?): Promise<T>` — reads `import.meta.env.VITE_API_BASE` + `VITE_API_KEY`, sets `X-API-Key` if non-empty, throws `ApiError` on non-2xx (parses JSON body)
  - Convenience: `get`, `put`, `post`, `del` wrappers
  - For DELETE that returns 204 or text, handle empty body
- [x] 2.5 `web/src/api/sse.ts`:
  - `fetchEventStream(path, {signal, body, onEvent})` — POST with `X-API-Key`, stream response body, parse SSE frames line-by-line, invoke `onEvent({type, data})`, return a promise that resolves when the stream ends
  - Skip lines starting with `:` (comments/heartbeat)
  - Lines of the form `event: X` set the next frame's type; `data: Y` set payload (multi-line data concatenates with newline); blank line commits the frame
- [x] 2.6 `web/src/hooks/useAsync.ts` — `useAsync<T>(fn, deps): {data, error, loading, reload}` with abort on unmount

## 3. Layout + router

- [x] 3.1 `web/src/components/Layout.tsx` — fixed top bar ("mas-pipeline"), centered content container, `<Outlet />`
- [x] 3.2 `web/src/App.tsx` — `<Routes>` with:
  - `/` → `ProjectsPage`
  - `/projects/:id` → `ProjectDetailPage`
  - `/projects/:id/runs/:runId` → `RunDetailPage`
  - Wrap all routes in `<Layout>`

## 4. Pages

- [x] 4.1 `web/src/pages/ProjectsPage.tsx`:
  - On mount: `client.get<ProjectList>('/projects')`
  - Render list of cards showing `id`, `name`, `pipeline`, `status`
  - Card click navigates to `/projects/:id`
  - Inline error block on failure, loading state
- [x] 4.2 `web/src/pages/ProjectDetailPage.tsx`:
  - Fetch `GET /projects/:id` for header
  - Read `?tab=` query param, default `agents`
  - Render tab bar (agents/pipelines/runs) with active styling
  - Conditional render `<AgentsTab projectId=... />`, `<PipelinesTab ... />`, `<RunsTab ... />`
- [x] 4.3 `web/src/pages/RunDetailPage.tsx`:
  - Reads `:id` and `:runId` params
  - On mount: fetch `GET /runs/:runId` for current status
  - If triggered via `state.triggerInput`, call `fetchEventStream('/projects/:id/pipelines/:pipe/runs?stream=true', {onEvent})` and append events to a local array
  - Render event log (scrollable, fixed-height panel); show final status

## 5. Tab components

- [x] 5.1 `web/src/components/AgentsTab.tsx`:
  - Fetches `GET /projects/:id/agents` (merged view)
  - Renders list of rows: `{name, source}` with badge class (`global` gray, `project-only` green, `project-override` amber)
  - Row click opens `<FileEditor>` for that agent (read + edit project layer)
  - "New agent" button opens editor with empty content
- [x] 5.2 `web/src/components/PipelinesTab.tsx`: mirror of `AgentsTab` pointing at `/pipelines`
- [x] 5.3 `web/src/components/RunsTab.tsx`:
  - Shows a "Trigger" form: pipeline name dropdown (from `PipelinesTab`'s data), user_input textarea, Go button
  - On submit: navigates to `/projects/:id/runs/new?pipeline=X&input=Y` (no — just trigger and navigate with returned run_id). Actually: `client.post('/projects/:id/pipelines/:name/runs', {input: {...}})` returns `{run_id}`, then `navigate('/projects/:id/runs/:runId')`.
  - Streaming view lives in `RunDetailPage`
- [x] 5.4 `web/src/components/FileEditor.tsx`:
  - Props: `{ projectId, kind: 'agent'|'pipeline', name: string, initialContent: string, onSaved }`
  - `<textarea>` with monospace font + tab key capture (soft tab = 2 spaces)
  - "Save" button → `PUT /projects/:id/{agents|pipelines}/:name` → calls `onSaved`
  - Shows inline error on 422/409 with structured message
  - "Delete" button → DELETE, handles 409 (agent) with references list rendered inline

## 6. Tests

- [x] 6.1 `web/src/__tests__/client.test.ts`:
  - Mocks global `fetch`
  - Asserts `X-API-Key` header present when `VITE_API_KEY` set; absent when empty
  - Asserts `Content-Type: application/json` on PUT/POST with body
  - Asserts `ApiError` thrown on 404 with `detail` preserved
  - Asserts 204 returns `undefined` without parse error
- [x] 6.2 `web/src/__tests__/sse.test.ts`:
  - Constructs a `ReadableStream` from a fixed byte array containing a 3-event SSE payload (`event: pipeline_start\ndata: {"run_id":"x"}\n\n`, a `: ping`, a `event: pipeline_end\ndata: {}\n\n`)
  - Calls `fetchEventStream` with a mocked fetch returning the stream
  - Verifies `onEvent` called twice with correct `{type, data}`
  - Verifies parser doesn't choke on `:` heartbeats

## 7. Validation gates

- [x] 7.1 `cd web && npm run typecheck` — must pass (`tsc --noEmit`)
- [x] 7.2 `cd web && npm run test` — vitest green
- [x] 7.3 `cd web && npm run build` — produces `web/dist/index.html` + assets
- [x] 7.4 `openspec validate add-web-frontend-mvp --strict`

## 8. Archive + commit

- [x] 8.1 Update `.plan/progress.md` — Phase 6.4 step 5 entry
- [x] 8.2 `openspec archive add-web-frontend-mvp --yes`
- [x] 8.3 `git commit`
