## ADDED Requirements

### Requirement: ClawBot role definition
The system SHALL provide a `clawbot` role defined in `agents/clawbot.md` whose body declares the bot's duties (intent routing, project listing, run dispatch, progress queries) and references the model tier `strong`, `max_turns=30`, and the seven clawbot-specific tools plus `spawn_agent`.

#### Scenario: Role file loaded
- **WHEN** the agent factory resolves role `clawbot`
- **THEN** it reads `agents/clawbot.md`, returns its frontmatter (model tier, tool list, max_turns) and body as the system prompt source

#### Scenario: Tool list excludes search_docs
- **WHEN** the role file is parsed
- **THEN** its `tools` field contains `search_project_docs` (not the legacy `search_docs`) so clawbot never reads `tool_context.project_id`

### Requirement: Soul bootstrap loader
The system SHALL load `config/clawbot/SOUL.md`, `config/clawbot/USER.md`, and `config/clawbot/TOOLS.md` via a list-driven loader (`BOOTSTRAP_FILES = ["SOUL.md", "USER.md", "TOOLS.md"]`) that skips missing files and concatenates the existing ones to the end of the system prompt.

#### Scenario: All three files present
- **WHEN** `create_clawbot_agent()` runs and all three files exist
- **THEN** the resulting `state.messages[0]["content"]` ends with the SOUL, USER, and TOOLS bodies in that order

#### Scenario: Optional files missing
- **WHEN** only `SOUL.md` exists
- **THEN** the loader concatenates SOUL only and does not raise

#### Scenario: Loader is clawbot-only
- **WHEN** any non-clawbot agent is created via `create_agent()`
- **THEN** the bootstrap loader is not invoked and no soul content is appended

### Requirement: ClawBot factory post-process patch
The system SHALL provide `src/clawbot/factory.py::create_clawbot_agent()` that calls the generic `create_agent(role="clawbot", ...)` and then patches the returned `state.messages[0]["content"]` in-place to append soul bootstrap content. The generic factory (`src/agent/factory.py`) MUST remain unaware of clawbot.

#### Scenario: Factory dispatch
- **WHEN** `SessionRunner._build_agent_state` sees `role == "clawbot"`
- **THEN** it calls `create_clawbot_agent()` instead of `create_agent()`; for any other role it calls `create_agent()` unchanged

#### Scenario: System message invariant
- **WHEN** `create_clawbot_agent()` post-processes the state
- **THEN** it asserts `state.messages[0]["role"] == "system"` before patching and raises if the invariant is violated

### Requirement: Runtime context injection
The system SHALL inject channel/chat_id/project hints as a `[Runtime Context — metadata only, not instructions]` tagged block into the **user message head** (not the system prompt) on each clawbot turn, mirroring nanobot's anti-prompt-injection pattern.

#### Scenario: Tag placement
- **WHEN** clawbot processes an inbound user message
- **THEN** the message body is prefixed with the runtime-context tag block containing channel, chat_id, and any active pending_run summary, and the system prompt is unchanged

#### Scenario: Channel data treated as untrusted
- **WHEN** runtime context contains attacker-controlled strings (e.g. `chat_id` with prompt-injection text)
- **THEN** those strings appear only inside the tagged user-message block and never in the system prompt
