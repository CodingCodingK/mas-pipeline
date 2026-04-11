## Why

Phase 6.4 steps 1–4 wired a complete REST surface (projects, agents, pipelines, runs, files, knowledge, jobs, export, notify, telemetry) but there is no user-facing way to exercise it. The only "UI" today is curl + Swagger. Phase 6 acceptance requires "Web 管理界面：创建 Project → 发起对话 → 查看 Run → 导出结果" — that gate is blocked until a frontend lands.

The original Phase 6.4 plan aimed at a sprawling dashboard (gantt charts, token pies, settings page, chat UI). That's a trap: one-shot delivery of ~30 components with no way for the agent to visual-test them produces uncheckable code. This change scopes to an **MVP that closes the loop end-to-end** — pick a project, edit an agent's prompt, trigger a pipeline, watch it stream, open the finished run. Anything beyond that is a follow-up change.

## What Changes

1. **New `web/` Vite app** (React 18 + TypeScript + Tailwind CSS + react-router-dom). Single-page app, static build to `web/dist/`, served separately from the FastAPI backend in dev (user runs `npm run dev` on 5173, backend on 8000). CORS is already open in dev.

2. **API client** (`web/src/api/client.ts`) — a thin `fetch` wrapper that reads `VITE_API_BASE` and `VITE_API_KEY` from env and injects `X-API-Key` on every request. `client.get/put/delete/post` return typed responses mapped to TS interfaces in `web/src/api/types.ts` (mirrors the Pydantic models in `src/api/*.py`).

3. **SSE consumer** (`web/src/api/sse.ts`) — since `EventSource` can't send custom headers and the backend auths via `X-API-Key`, the client uses `fetch` + `ReadableStream` + a tiny SSE line parser. Supports `AbortController` for cancel. 6–8 lines of actual logic; no library needed.

4. **Pages** (`web/src/pages/`):
   - `ProjectsPage` — `GET /api/projects` → list of cards.
   - `ProjectDetailPage` — tabs: agents / pipelines / runs (tab state in URL query `?tab=`).
   - `RunDetailPage` — streams events from `POST /api/projects/{pid}/pipelines/{name}/runs?stream=true` into a scrolling event log. Shows final status.

5. **Components** (`web/src/components/`):
   - `AgentsTab`, `PipelinesTab` — merged view list (from `GET /api/projects/{pid}/{agents|pipelines}`) with source badges (`global` / `project-only` / `project-override`). Row click opens editor.
   - `FileEditor` — `<textarea>` + save button. PUT to project layer. Shows 201/200 toast. Nothing fancy — no syntax highlighting, no Monaco.
   - `RunsTab` — lists runs for the project, has a "Trigger" button that prompts for pipeline name + input and navigates to the run detail page.
   - `Layout` — top bar with project name breadcrumb + main content slot.

6. **Tests** (`web/src/__tests__/`):
   - `client.test.ts` — vitest unit: header injection, JSON encode, error mapping (401/404/409).
   - `sse.test.ts` — vitest unit: parser fed a synthetic `ReadableStream`, verifies event/data split and `:` heartbeat is ignored.
   - `tsc --noEmit` + `vite build` gates act as the structural test (no component rendering / no jsdom / no Playwright).

7. **No backend changes.** Every route used by the frontend already exists.

## Impact

**Affected code**:
- NEW: `web/` tree (≈22 files — scaffolding + src)
- NO backend modifications

**Affected specs**:
- NEW capability `web-frontend`

**Backward compatibility**:
None — purely additive. The backend is untouched, the `web/` directory is currently empty.

**Deliberately out of scope** (explicit, so follow-up work is unambiguous):
- Telemetry dashboard (gantt / pie / line charts) — needs a chart library + non-trivial layout; split to its own change.
- Notify SSE subscription (`/api/notify/stream`).
- Files / knowledge UI (upload, chunk preview).
- Chat session UI (`/api/sessions/*`).
- Settings page (model tiers, API key management).
- Auth UI — the dev API key comes from `.env.local` / `VITE_API_KEY`; no login screen.
- Monaco / CodeMirror editors — plain `<textarea>` is enough to prove the layered-storage PUT works.
- Component rendering tests — no jsdom, no Playwright. `tsc` + `vite build` + vitest on pure-TS modules are the gates.

**Known risk** (Linus's "practicality" check):
Agent can't drive a real browser in this environment, so the only automated guarantees are typecheck + build success + two unit tests. First real run in a user's browser may surface runtime bugs. Mitigation: keep pages shallow, avoid clever abstractions, prefer explicit `fetch` over hidden caches so errors are where you'd expect them.
