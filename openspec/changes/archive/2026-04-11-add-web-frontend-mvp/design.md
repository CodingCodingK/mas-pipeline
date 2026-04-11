## Decisions

### 1. Vite + React + TS + Tailwind, no meta-framework

- **Chosen**: Vite 5, React 18, TypeScript 5, Tailwind CSS 3, react-router-dom 6.
- **Rejected**: Next.js (SSR overhead for a pure SPA talking to an external API); Create React App (deprecated); Remix (routing conventions collide with our URL scheme).
- **Rationale**: we ship a static SPA + separate FastAPI backend. Vite gives sub-second dev reload and a deterministic `dist/` bundle, with zero server runtime.

### 2. No shadcn/ui, no component library

- **Chosen**: raw Tailwind utilities + ≤5 hand-written components.
- **Rejected**: shadcn/ui (CLI-installed generated boilerplate, generates 20+ files we won't use), Radix (too much surface area), Material-UI (heavy).
- **Rationale**: MVP has five distinct visual elements (card, tab bar, list row, textarea, button). Adding a component library is more LoC than writing them.

### 3. No TanStack Query

- **Chosen**: a ~30-line `useAsync<T>(fn, deps)` hook — returns `{data, error, loading, reload}`.
- **Rejected**: TanStack Query (caching, invalidation, retries — all unused by an MVP with 3 pages and manual refetch-after-mutate).
- **Rationale**: the MVP has no background refetch, no stale-while-revalidate, no pagination. `useAsync` + explicit `reload()` after save is simpler and the code is obvious.

### 4. SSE via `fetch` + `ReadableStream`, not `EventSource`

- **Chosen**: `fetchEventStream(url, {signal, onEvent})` — reads body as `ReadableStream<Uint8Array>`, decodes UTF-8, parses line-by-line into `{event, data}` records.
- **Rejected**: native `EventSource` (cannot set `X-API-Key` header; query-param auth would require a backend change that leaks the key into logs); third-party libraries (`eventsource-parser`, `@microsoft/fetch-event-source` — unnecessary for ~30 lines of parser).
- **Rationale**: zero backend change, standard Fetch API, supports `AbortController` natively. The parser is small enough to unit-test.

### 5. Tab state lives in the URL

- **Chosen**: `?tab=agents|pipelines|runs` as a query param, read via `useSearchParams`.
- **Rejected**: React state in the page component (tab resets on reload), nested routes (more router surface for no benefit in an MVP).
- **Rationale**: URL is shareable, back button works, page reload doesn't lose context. Zero cost to implement.

### 6. File editing uses `<textarea>`, not a code editor

- **Chosen**: plain `<textarea>` with monospace Tailwind class + tab key interception (soft tab = 2 spaces).
- **Rejected**: Monaco (2MB bundle), CodeMirror (still ~500KB), highlight.js (adds a parse step).
- **Rationale**: the whole point of Change 2 was that layered storage works with plain text files. A textarea proves PUT/GET roundtrip. Syntax highlighting is a cosmetic follow-up.

### 7. Server source badge rendering

- **Chosen**: pure Tailwind pill — `global` gray, `project-only` green, `project-override` amber. Three className branches, no abstraction.
- **Rationale**: three cases, three classNames. A `Badge` component wrapping a switch is more code than the switch itself.

### 8. Error handling shape

- **Chosen**: `client.ts` throws `ApiError{status, detail, body}` on non-2xx. Pages catch at the page level and render an inline error block with the detail string. 409 with a `references` array (from agent delete) shows a special "in use by" list.
- **Rejected**: global error boundary + toast library.
- **Rationale**: three places that can error (list load, save, delete). Inline messages are adequate and debuggable.

### 9. No authentication UI

- **Chosen**: `VITE_API_KEY` env variable, baked into the build. If the backend has `api_keys: []` (dev mode), an empty string works.
- **Rejected**: login form (backend has no user session endpoint); localStorage-based key entry (leaks in shared machines).
- **Rationale**: this is a dev tool; real auth is a downstream concern. Phase 7 will revisit deployment auth.

### 10. Tests: typecheck + build + two vitest files

- **Chosen gates**:
  - `npm run typecheck` (`tsc --noEmit`)
  - `npm run build` (`vite build`)
  - `npm run test` (`vitest run`)
- **Covered by vitest**:
  - `client.test.ts` — header injection, success/error mapping (mocked `fetch`)
  - `sse.test.ts` — parser handles `event:` + `data:` pairs, skips `:` heartbeats, unsubscribes on `pipeline_end`
- **NOT covered**: no jsdom, no component rendering, no Playwright, no visual regression.
- **Rationale**: the failure modes an agent can't introspect (layout, hover, ARIA) are out of scope for an MVP delivered without browser access. What we can verify (compile, build, pure logic) we verify rigorously.

## Open questions

None — all decisions above are lockable without user input for an MVP.

## Risks

- **Runtime bugs first appear in the browser**: with no jsdom, any runtime issue in rendering paths only surfaces when a user runs `npm run dev`. Mitigation: shallow pages, obvious control flow, no hidden state.
- **Vite/React/TS dep drift**: pinning exact versions in `package.json` + `package-lock.json` kept in git.
- **Backend API drift**: TS types in `api/types.ts` are hand-maintained mirrors of Pydantic models. When backend models change, the frontend types must change in lockstep. Documented in the spec as a maintenance contract.
