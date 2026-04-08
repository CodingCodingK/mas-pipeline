## ADDED Requirements

### Requirement: Token estimation
`estimate_tokens(messages: list[dict]) -> int` SHALL estimate the total token count for a list of messages. The estimation SHALL use `len(json.dumps(msg, ensure_ascii=False)) / 4` as a character-based approximation. An optional `tiktoken` path MAY be supported in the future but is not required for Phase 3.

#### Scenario: Empty messages
- **WHEN** `estimate_tokens([])` is called
- **THEN** it SHALL return `0`

#### Scenario: Simple messages
- **WHEN** `estimate_tokens([{"role": "user", "content": "Hello world"}])` is called
- **THEN** it SHALL return an approximate token count based on character length / 4

#### Scenario: Messages with tool results
- **WHEN** messages contain large tool_result outputs (e.g., 10000 chars)
- **THEN** the estimate SHALL reflect the full content size

### Requirement: Context window resolution
`get_context_window(model: str) -> int` SHALL return the context window size for a given model name.

Lookup priority:
1. `settings.context_windows` dict (user-configured overrides)
2. Built-in `_DEFAULT_CONTEXT_WINDOWS` dict (hardcoded common models)
3. Fallback: `128000` (DEFAULT_CONTEXT_WINDOW constant)

Built-in defaults SHALL include at minimum: gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5, gemini-2.5-pro, gemini-2.5-flash, deepseek-chat, deepseek-reasoner.

#### Scenario: Known model with no config override
- **WHEN** `get_context_window("gpt-4o-mini")` is called and settings has no context_windows section
- **THEN** it SHALL return `128000` from the built-in defaults

#### Scenario: Config override takes precedence
- **WHEN** settings.context_windows has `{"gpt-4o-mini": 64000}` and `get_context_window("gpt-4o-mini")` is called
- **THEN** it SHALL return `64000`

#### Scenario: Unknown model uses fallback
- **WHEN** `get_context_window("some-unknown-model")` is called
- **THEN** it SHALL return `128000`

### Requirement: Compact threshold calculation
`get_thresholds(model: str) -> CompactThresholds` SHALL compute thresholds from model context window and percentage-based settings.

```
context_window = get_context_window(model)
autocompact_threshold = context_window * settings.compact.autocompact_pct
blocking_limit = context_window * settings.compact.blocking_pct
```

`CompactThresholds` SHALL be a dataclass with fields: `context_window`, `autocompact_threshold`, `blocking_limit`.

Default percentages in settings: `autocompact_pct=0.85`, `blocking_pct=0.95`.

#### Scenario: Default thresholds for 128K model
- **WHEN** `get_thresholds("gpt-4o-mini")` is called with default settings
- **THEN** `autocompact_threshold` SHALL be `108800` (128000 * 0.85) and `blocking_limit` SHALL be `121600` (128000 * 0.95)

#### Scenario: Custom percentages
- **WHEN** settings has `compact.autocompact_pct=0.80` and `get_thresholds("gpt-4o-mini")` is called
- **THEN** `autocompact_threshold` SHALL be `102400` (128000 * 0.80)

### Requirement: Microcompact clears old tool results
`micro_compact(messages: list[dict], keep_recent: int = 3) -> list[dict]` SHALL replace the `content` of old tool-result messages with `"[Old tool result cleared]"`, keeping only the most recent `keep_recent` tool-result messages intact.

Tool-result messages are identified by `role == "tool"`.

The function SHALL modify messages in-place and return the same list.

#### Scenario: Recent tool results preserved
- **WHEN** messages contain 5 tool-result messages and `micro_compact(messages, keep_recent=3)` is called
- **THEN** the 2 oldest tool-result messages SHALL have content replaced with `"[Old tool result cleared]"`, and the 3 newest SHALL remain unchanged

#### Scenario: Fewer than keep_recent tool results
- **WHEN** messages contain 2 tool-result messages and `keep_recent=3`
- **THEN** no tool results SHALL be modified

#### Scenario: Non-tool messages untouched
- **WHEN** messages contain user, assistant, and system messages
- **THEN** microcompact SHALL not modify them

### Requirement: Autocompact generates summary and replaces history
`auto_compact(messages: list[dict], adapter: LLMAdapter, model: str) -> CompactResult` SHALL:
1. Compute a split point: keep the most recent messages that fit within 30% of context_window tokens
2. Send the older messages to a light-tier LLM with a summary prompt
3. The summary prompt SHALL instruct the LLM to preserve: key decisions, file paths, code snippets, error messages, and task progress
4. Replace the older messages with a single `{"role": "user", "content": "<summary>"}` message prefixed with `[CONVERSATION SUMMARY]`
5. Store the summary in PG `compact_summaries` table via `save_compact_summary(session_id, summary, token_count)`
6. Return `CompactResult(messages=<new_messages>, summary=<summary_text>, tokens_before=<int>, tokens_after=<int>)`

#### Scenario: Autocompact triggered
- **WHEN** messages have 100 entries totaling ~120K estimated tokens and autocompact_threshold is 108K
- **THEN** `auto_compact` SHALL split messages, generate a summary of the older portion, and return a shorter message list starting with the summary

#### Scenario: Summary preserves key information
- **WHEN** older messages contain file paths, error messages, and decisions
- **THEN** the generated summary SHALL retain those details

#### Scenario: Compact summary persisted
- **WHEN** `auto_compact` completes successfully
- **THEN** a row SHALL be inserted into `compact_summaries` with the summary text and token count

### Requirement: Reactive compact on context_length_exceeded
`reactive_compact(messages: list[dict], adapter: LLMAdapter, model: str) -> CompactResult` SHALL perform the same logic as autocompact but with a more aggressive split point (keep only 20% of context_window worth of recent messages).

This function is called when the LLM returns a `context_length_exceeded` error.

#### Scenario: Reactive compact after LLM error
- **WHEN** LLM returns context_length_exceeded and `reactive_compact` is called
- **THEN** it SHALL aggressively summarize, keeping fewer recent messages than autocompact

#### Scenario: Reactive compact reduces below limit
- **WHEN** reactive_compact is called on messages over the blocking_limit
- **THEN** the resulting messages SHALL estimate below the blocking_limit

### Requirement: CompactResult dataclass
`CompactResult` SHALL be a dataclass with fields: `messages` (list[dict]), `summary` (str), `tokens_before` (int), `tokens_after` (int).

#### Scenario: CompactResult construction
- **WHEN** CompactResult is created with all fields
- **THEN** all fields SHALL be accessible as attributes

### Requirement: CompactSummary ORM model
The system SHALL define a `CompactSummary` SQLAlchemy ORM model in `src/models.py` mapping to the existing `compact_summaries` table.

#### Scenario: CompactSummary model fields
- **WHEN** CompactSummary model is inspected
- **THEN** it SHALL have fields: `id` (int PK), `session_id` (str), `summary` (str), `token_count` (int nullable), `created_at`
