## MODIFIED Requirements

### Requirement: Autocompact generates summary and appends to history
`auto_compact(messages: list[dict], adapter: LLMAdapter, model: str) -> CompactResult` SHALL:

1. Compute a split point: keep the most recent messages that fit within ~30% of the model's context window (estimated via `estimate_tokens`). Messages before the split point are the "older messages" to be summarized.
2. Send the older messages to the caller-provided `adapter` with a summary prompt. The `model` parameter SHALL be the same model the main agent loop is running on — NOT a separate cheap / light tier. The summary prompt SHALL instruct the LLM to preserve key decisions, file paths, code snippets, error messages, and task progress.
3. If the summarizer call fails with a prompt-too-long / context-exceeded error, drop the oldest ~50% of the older-messages blob and retry. Retry SHALL be capped at 2 attempts; after two failed attempts `auto_compact` SHALL raise the underlying error to the caller (which will count it against the circuit breaker).
4. On success, APPEND two new messages to the TAIL of the original messages list:
   - A summary message: `{"role": "user", "content": "<summary>", "metadata": {"is_compact_summary": true}}`
   - A boundary marker: `{"role": "system", "content": "", "metadata": {"is_compact_boundary": true, "turn": <current_turn>}}`
5. The pre-compact messages SHALL remain in the returned list untouched. `auto_compact` SHALL NOT replace, delete, or reorder any existing message. Compact is an append-only operation on the in-memory list.
6. Return `CompactResult(messages=<appended_list>, summary=<summary_text>, tokens_before=<int>, tokens_after=<int>)`, where `tokens_after` is the token count of the post-boundary slice (the portion the model will actually see on the next turn).

`auto_compact` SHALL NOT persist the summary to a separate database table. Persistence to `conversations.messages` is handled by the calling SessionRunner via its existing append-on-change path.

#### Scenario: Autocompact triggered
- **WHEN** messages have 100 entries totaling ~120K estimated tokens and autocompact_threshold is 108K
- **THEN** `auto_compact` SHALL generate a summary of the older portion and return a list whose length is `len(original) + 2` (original messages + summary + boundary marker)

#### Scenario: Summary preserves key information
- **WHEN** older messages contain file paths, error messages, and decisions
- **THEN** the generated summary SHALL retain those details

#### Scenario: Compact does not shrink the message list
- **WHEN** `auto_compact` returns successfully
- **THEN** every message present in the input list SHALL still be present at the same index in the returned list
- **AND** the returned list SHALL be exactly two entries longer than the input (summary + boundary marker)

#### Scenario: Summary uses main agent adapter
- **WHEN** `auto_compact` is called with `adapter=main_adapter, model="claude-sonnet-4-6"`
- **THEN** the summary LLM call SHALL use `main_adapter` with `model="claude-sonnet-4-6"`
- **AND** no call to `route("light")` or any other tier resolver SHALL occur inside `auto_compact`

#### Scenario: Prompt-too-long retry with head drop
- **WHEN** the first summarizer call fails with a context-exceeded error
- **THEN** `auto_compact` SHALL drop the oldest half of the older-messages blob and retry
- **AND** if the retry succeeds, the returned `CompactResult.summary` SHALL reflect only the retained (newer half of older) messages

#### Scenario: Retry cap exhausted
- **WHEN** both the initial call and the retry fail with context-exceeded errors
- **THEN** `auto_compact` SHALL raise the underlying `LLMError`
- **AND** the caller (SessionRunner) SHALL count this against `consecutive_compact_failures`

### Requirement: Reactive compact on context_length_exceeded
`reactive_compact(messages: list[dict], adapter: LLMAdapter, model: str) -> CompactResult` SHALL perform the same append-only logic as `auto_compact` but with a more aggressive split point (keep only 20% of context_window worth of recent messages before the boundary marker, instead of 30%).

This function is called when the LLM returns a `context_length_exceeded` error on a regular turn.

Like `auto_compact`, reactive compact SHALL:
- Use the caller-provided main agent adapter (no `route("light")`)
- Append summary + boundary marker rather than replacing the list
- Apply the same 2-attempt retry-with-head-drop on summarizer overflow

#### Scenario: Reactive compact after LLM error
- **WHEN** LLM returns context_length_exceeded and `reactive_compact` is called
- **THEN** it SHALL aggressively summarize, keeping fewer recent messages after the boundary marker than autocompact would

#### Scenario: Reactive compact reduces below limit
- **WHEN** reactive_compact is called on messages over the blocking_limit
- **THEN** the post-boundary slice token count SHALL estimate below the blocking_limit

#### Scenario: Reactive compact is append-only
- **WHEN** reactive_compact returns successfully
- **THEN** every original message SHALL still be present at the same index
- **AND** the returned list SHALL contain a `is_compact_summary` entry followed by an `is_compact_boundary` entry appended to the tail

