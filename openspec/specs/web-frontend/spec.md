# web-frontend Specification

## Purpose
TBD - created by archiving change add-web-frontend-mvp. Update Purpose after archive.
## Requirements
### Requirement: Vite + React + TypeScript SPA scaffolding

The repository SHALL include a `web/` directory containing a standalone Vite project configured for React 18, TypeScript 5, and Tailwind CSS 3. The project SHALL produce a static bundle via `npm run build` into `web/dist/` and be served independently of the FastAPI backend during development.

The project SHALL provide the following npm scripts:

- `dev` — start Vite dev server (default port 5173)
- `build` — `vite build`
- `typecheck` — `tsc --noEmit`
- `test` — `vitest run`

The project's TypeScript configuration SHALL enable `strict: true` and configure a path alias `@/*` resolving to `src/*`.

#### Scenario: Build succeeds from a clean checkout

- **GIVEN** a fresh clone with `node_modules` absent
- **WHEN** a developer runs `cd web && npm install && npm run build`
- **THEN** the command SHALL exit with status 0
- **AND** `web/dist/index.html` SHALL exist after the build

#### Scenario: Typecheck rejects type errors

- **GIVEN** any `.ts` / `.tsx` file with a type mismatch
- **WHEN** `npm run typecheck` runs
- **THEN** the command SHALL exit with non-zero status and print the error location

### Requirement: API client injects X-API-Key header

`web/src/api/client.ts` SHALL export a `request<T>(method, path, body?): Promise<T>` function and `get` / `put` / `post` / `del` convenience wrappers. The client SHALL read `import.meta.env.VITE_API_BASE` and `import.meta.env.VITE_API_KEY` at call time. When `VITE_API_KEY` is a non-empty string, the client SHALL attach it as an `X-API-Key` header on every request.

The client SHALL throw an `ApiError` subclass of `Error` carrying `{status: number, body: unknown}` when the response status is not in the 2xx range. A 204 response SHALL resolve to `undefined` without attempting to parse the body.

#### Scenario: Header is added when key is configured

- **GIVEN** `VITE_API_KEY` is the string `"secret"`
- **WHEN** `client.get("/agents")` is invoked
- **THEN** the underlying `fetch` call SHALL include the header `X-API-Key: secret`

#### Scenario: Header is omitted when key is empty

- **GIVEN** `VITE_API_KEY` is an empty string (development mode)
- **WHEN** `client.get("/agents")` is invoked
- **THEN** the underlying `fetch` call SHALL NOT include an `X-API-Key` header

#### Scenario: Non-2xx response raises ApiError

- **GIVEN** a mocked `fetch` returning status 404 with body `{"detail":"agent not found"}`
- **WHEN** `client.get("/agents/nobody")` is awaited
- **THEN** the promise SHALL reject with an `ApiError` instance
- **AND** `error.status` SHALL equal `404`
- **AND** `error.body.detail` SHALL equal `"agent not found"`

#### Scenario: 204 response resolves undefined

- **GIVEN** a mocked `fetch` returning status 204 with an empty body
- **WHEN** `client.del("/agents/writer")` is awaited
- **THEN** the promise SHALL resolve to `undefined`

### Requirement: SSE consumer via fetch + ReadableStream

`web/src/api/sse.ts` SHALL export `fetchEventStream(path, {signal?, body?, onEvent})` that posts to the given path with the API key header attached, reads the response body as a UTF-8 byte stream, and parses Server-Sent Event frames. For every complete frame, it SHALL invoke `onEvent({type: string, data: string})`. The function SHALL return a promise that resolves when the stream closes normally and rejects when it errors or the `AbortSignal` fires.

The parser SHALL:
- Accept lines of the form `event: <type>` setting the frame type
- Accept lines of the form `data: <payload>` as the frame data
- Ignore lines starting with `:` (heartbeat comments)
- Treat a blank line as the frame delimiter, after which `onEvent` SHALL be called
- Reset the pending type to `"message"` after each emitted frame

#### Scenario: Parses event and data lines into frames

- **GIVEN** a `ReadableStream` yielding the bytes of `"event: pipeline_start\ndata: {\"run_id\":\"x\"}\n\nevent: pipeline_end\ndata: {}\n\n"`
- **WHEN** `fetchEventStream(...)` runs with a mocked fetch returning this stream
- **THEN** `onEvent` SHALL be called exactly twice
- **AND** the first call SHALL receive `{type: "pipeline_start", data: "{\"run_id\":\"x\"}"}`
- **AND** the second call SHALL receive `{type: "pipeline_end", data: "{}"}`

#### Scenario: Heartbeat lines are ignored

- **GIVEN** a stream containing `": ping\n\n"` between two real events
- **WHEN** `fetchEventStream` parses the stream
- **THEN** no `onEvent` call SHALL be emitted for the heartbeat
- **AND** the two real events SHALL still be emitted correctly

### Requirement: Projects list page

`web/src/pages/ProjectsPage.tsx` SHALL render a list view of all projects fetched from `GET /api/projects`. Each project SHALL be displayed as a card showing its `id`, `name`, `pipeline`, and `status`. Clicking a card SHALL navigate to `/projects/:id`.

The page SHALL render a loading placeholder while the fetch is in flight, an inline error message on failure, and an empty-state message when the response has zero items.

#### Scenario: Lists projects on mount

- **GIVEN** the backend returns two projects
- **WHEN** the page mounts
- **THEN** two cards SHALL be rendered in the document

#### Scenario: Shows error on fetch failure

- **GIVEN** the backend returns 401
- **WHEN** the page mounts
- **THEN** an error block SHALL be shown containing the status and detail

### Requirement: Project detail page with agent/pipeline/run tabs

`web/src/pages/ProjectDetailPage.tsx` SHALL render a tab container for a single project. The active tab SHALL be stored in the URL as a `?tab=` query parameter with one of the values `agents`, `pipelines`, or `runs` (default `agents`). Each tab SHALL render its own component fetching the appropriate REST endpoints:

- `AgentsTab` → `GET /api/projects/:id/agents` (merged view)
- `PipelinesTab` → `GET /api/projects/:id/pipelines` (merged view)
- `RunsTab` → `GET /api/projects/:id/runs` (run list, if endpoint exists) plus a "Trigger" form

The merged-view tabs SHALL display each item's `source` field as a colored pill (`global` / `project-only` / `project-override`). Clicking a row SHALL open an inline file editor.

#### Scenario: Tab state persists in URL

- **GIVEN** the user is on `/projects/1?tab=pipelines`
- **WHEN** the page renders
- **THEN** the pipelines tab SHALL be active

#### Scenario: Source pill reflects merged-view value

- **GIVEN** the merged view returns `[{name: "writer", source: "project-override"}]`
- **WHEN** `AgentsTab` renders
- **THEN** the row for `writer` SHALL display a pill labeled `project-override`
- **AND** the pill SHALL use the amber Tailwind color class

### Requirement: File editor component writes to project layer

`web/src/components/FileEditor.tsx` SHALL render a `<textarea>` containing the current agent or pipeline content, a "Save" button, and a "Delete" button. Saving SHALL issue `PUT /api/projects/:id/{agents|pipelines}/:name` with `{content}`. Deleting SHALL issue `DELETE /api/projects/:id/{agents|pipelines}/:name`.

Invalid names (422) and in-use agents (409 with `references` array) SHALL render their errors inline. The editor SHALL NOT provide syntax highlighting — plain text with monospace font is sufficient for the MVP.

#### Scenario: Save issues PUT with content

- **GIVEN** the editor is open for `writer` in project 42
- **WHEN** the user edits the textarea and clicks Save
- **THEN** the client SHALL send `PUT /api/projects/42/agents/writer` with the edited content in the body

#### Scenario: 409 on delete renders references inline

- **GIVEN** the backend returns 409 with `{detail: "...", references: [{project_id: null, pipeline: "blog", role: "writer"}]}`
- **WHEN** the user clicks Delete
- **THEN** an inline error SHALL render listing the blocking pipeline references

### Requirement: Run detail page streams events via SSE

`web/src/pages/RunDetailPage.tsx` SHALL stream events from `POST /api/projects/:id/pipelines/:name/runs?stream=true` when the page is entered with a pending trigger. It SHALL render a scrollable event log showing every event type and timestamp, and display the run's final status when the stream closes with `pipeline_end` or `pipeline_failed`.

The page SHALL also support loading a completed run by fetching `GET /api/runs/:runId` on mount when no pending trigger is present.

#### Scenario: Streams live events

- **GIVEN** a running pipeline emits three events then closes
- **WHEN** the page streams the run
- **THEN** the event log SHALL contain three rows in emission order
- **AND** the final status SHALL be "completed"

### Requirement: Vitest covers client and SSE parser

The repository SHALL include vitest tests under `web/src/__tests__/` that verify the API client header behavior, error mapping, and 204 handling, and verify the SSE parser against a canned `ReadableStream`. `npm run test` inside `web/` SHALL run these tests via `vitest run` and exit with status 0 when they pass.

Component-level rendering tests (jsdom, React Testing Library) are explicitly out of scope for this change and SHALL NOT be added.

#### Scenario: Vitest suite passes

- **WHEN** `cd web && npm run test` runs in a fresh checkout after `npm install`
- **THEN** the test runner SHALL exit with status 0
- **AND** both `client.test.ts` and `sse.test.ts` SHALL be reported as passing

