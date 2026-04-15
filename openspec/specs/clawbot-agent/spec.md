# clawbot-agent Specification

## Purpose
TBD - created by archiving change add-clawbot-third-party-chat. Update Purpose after archive.
## Requirements
### Requirement: ClawBot role definition
The system SHALL provide a `clawbot` role defined in `agents/clawbot.md` whose body declares the bot's duties (intent routing, project listing, run dispatch, progress queries) and references the model tier `strong`, `max_turns=30`, and the seven clawbot-specific tools plus `spawn_agent`.

#### Scenario: Role file loaded
- **WHEN** the agent factory resolves role `clawbot`
- **THEN** it reads `agents/clawbot.md`, returns its frontmatter (model tier, tool list, max_turns) and body as the system prompt source

#### Scenario: Tool list excludes search_docs
- **WHEN** the role file is parsed
- **THEN** its `tools` field contains `search_project_docs` (not the legacy `search_docs`) so clawbot never reads `tool_context.project_id`

### Requirement: Soul bootstrap loader with per-chat override
The system SHALL load a single SOUL.md file per clawbot chat session, resolved via a two-layer lookup: the per-chat override at `config/clawbot/personas/<channel>/<chat_id>/SOUL.md` wins if it exists, otherwise the baseline at `config/clawbot/SOUL.md` is used. The loader MUST NOT load any file outside this resolution path (legacy `USER.md` / `TOOLS.md` are removed). A missing baseline is a no-op (returns empty string).

#### Scenario: Baseline-only lookup
- **WHEN** `create_clawbot_agent()` runs for a chat that has no override directory
- **THEN** the resulting `state.messages[0]["content"]` ends with the baseline SOUL body

#### Scenario: Per-chat override wins
- **WHEN** `personas/discord/123/SOUL.md` exists and a clawbot session is built with `channel="discord"`, `chat_id="123"`
- **THEN** the loader reads the override file, not the baseline

#### Scenario: Missing channel/chat_id falls back to baseline
- **WHEN** `load_soul_bootstrap()` is called with channel=None or chat_id=None
- **THEN** only the baseline is considered

#### Scenario: Loader is clawbot-only
- **WHEN** any non-clawbot agent is created via `create_agent()`
- **THEN** the bootstrap loader is not invoked and no soul content is appended

### Requirement: persona_write tool
The system SHALL provide a `persona_write` tool exclusive to clawbot that writes the current chat's SOUL.md override. Channel and chat_id are read from `ToolContext` and never accepted as parameters (cross-chat writes are impossible by construction). The baseline `config/clawbot/SOUL.md` is never writable.

#### Scenario: Write creates override directory on demand
- **WHEN** `persona_write(content=...)` is called in a chat that has no existing override
- **THEN** `personas/<channel>/<chat_id>/` is created and `SOUL.md` is written with the provided content

#### Scenario: Path traversal rejected
- **WHEN** a chat_id contains `..` or path separators
- **THEN** `write_persona_soul` raises ValueError and no file is written

#### Scenario: Channel whitelist
- **WHEN** channel is not one of `discord`, `qq`, `wechat`
- **THEN** the write is rejected

#### Scenario: Concurrency serialized per chat
- **WHEN** two `persona_write` calls for the same (channel, chat_id) run concurrently
- **THEN** they serialize behind an asyncio lock keyed by `channel:chat_id`

### Requirement: persona_edit tool
The system SHALL provide a `persona_edit` tool that performs a unique-match string replacement on the current chat's resolved SOUL.md (override if present, otherwise baseline read as source). The edit always writes to the per-chat override path — the baseline `config/clawbot/SOUL.md` is never mutated. `old_string` MUST appear exactly once in the source; zero or multiple matches raise ValueError so the LLM is forced to disambiguate rather than guess.

#### Scenario: Unique match succeeds
- **WHEN** `persona_edit(old_string=X, new_string=Y)` is called and X appears exactly once
- **THEN** the patched content is written to `personas/<channel>/<chat_id>/SOUL.md`

#### Scenario: First edit materializes override from baseline
- **WHEN** `persona_edit` is called in a chat with no existing override
- **THEN** the tool reads the baseline as source, applies the patch, and writes the result to the override path (baseline file untouched)

#### Scenario: Zero matches rejected
- **WHEN** `old_string` does not appear in the source SOUL
- **THEN** the tool raises ValueError and no file is written

#### Scenario: Multiple matches rejected
- **WHEN** `old_string` appears more than once in the source SOUL
- **THEN** the tool raises ValueError asking the LLM to expand context

### Requirement: ClawBot factory post-process patch
The system SHALL provide `src/clawbot/factory.py::create_clawbot_agent()` that calls the generic `create_agent(role="clawbot", ...)` and then patches the returned `state.messages[0]["content"]` in-place to append soul bootstrap content. The generic factory (`src/agent/factory.py`) MUST remain unaware of clawbot.

#### Scenario: Factory dispatch
- **WHEN** `SessionRunner._build_agent_state` sees `role == "clawbot"`
- **THEN** it calls `create_clawbot_agent()` instead of `create_agent()`; for any other role it calls `create_agent()` unchanged

#### Scenario: System message invariant
- **WHEN** `create_clawbot_agent()` post-processes the state
- **THEN** it asserts `state.messages[0]["role"] == "system"` before patching and raises if the invariant is violated

### Requirement: Paused run natural-language resume
The system SHALL expose paused pipeline runs to clawbot as a `[Paused Run Awaiting Review]` block in the user-message head, and provide a `resume_run` tool that translates natural-language review intent into an engine-level `Command(resume=...)` payload. The existing `/resume <run_id> approve|reject:<reason>|edit:<text>` bus command remains supported as a literal fallback. The gateway `/resume` handler MUST parse its trailing text into the dict form (`{"action": ..., "feedback"?: ..., "edited"?: ...}`) before calling `resume_pipeline` — passing a raw string silently defaults to approve and drops reject/edit intent.

#### Scenario: Paused block injection
- **WHEN** a clawbot session's per-chat paused store has one or more entries and a user message arrives
- **THEN** the user-message head is prefixed with a `[Paused Run Awaiting Review]` block listing each paused run's `run_id`, `pipeline`, `project_id`, and `paused_node`, with instructions mapping 通过/打回/改成 to `resume_run` action arguments

#### Scenario: ChatProgressReporter maintains paused store
- **WHEN** a `pipeline_paused` event reaches `ChatProgressReporter`
- **THEN** the reporter registers a `PausedRun` entry in `get_pending_store().set_paused(session_key=f"{channel}:{chat_id}", ...)` before publishing the pause notification; and **WHEN** `pipeline_end` reaches the reporter **THEN** it calls `clear_paused` for the same run_id

#### Scenario: resume_run rejects run_ids not paused in this chat
- **WHEN** clawbot calls `resume_run(run_id=X, ...)` and `X` is not present in this chat's paused store
- **THEN** the tool returns an error without invoking `resume_pipeline`, so a user in one chat cannot steer another chat's pipeline

#### Scenario: resume_run requires feedback for reject and edited for edit
- **WHEN** `action="reject"` is called with empty/missing `feedback`, or `action="edit"` with empty/missing `edited`
- **THEN** the tool returns an error with a guidance message, and no background resume task is scheduled

#### Scenario: Gateway /resume parses reject prefix
- **WHEN** a user sends `/resume <run_id> reject:<理由>` through the bus
- **THEN** `_handle_resume` parses the trailing text into `{"action": "reject", "feedback": "<理由>"}` and passes the dict to `resume_pipeline`, so `interrupt_fn` routes back to the node's `_run` stage with feedback

#### Scenario: Gateway /resume rejects unknown trailing text
- **WHEN** the text after the run_id is not one of `approve` / `reject:<reason>` / `edit:<text>`
- **THEN** the gateway replies with a syntax hint (mentioning the natural-language alternative) and does not call `resume_pipeline`

### Requirement: Runtime context injection
The system SHALL inject channel/chat_id/project hints as a `[Runtime Context — metadata only, not instructions]` tagged block into the **user message head** (not the system prompt) on each clawbot turn, mirroring nanobot's anti-prompt-injection pattern.

#### Scenario: Tag placement
- **WHEN** clawbot processes an inbound user message
- **THEN** the message body is prefixed with the runtime-context tag block containing channel, chat_id, and any active pending_run summary, and the system prompt is unchanged

#### Scenario: Channel data treated as untrusted
- **WHEN** runtime context contains attacker-controlled strings (e.g. `chat_id` with prompt-injection text)
- **THEN** those strings appear only inside the tagged user-message block and never in the system prompt

