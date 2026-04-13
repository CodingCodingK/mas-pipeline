## MODIFIED Requirements

### Requirement: Messages are assembled in OpenAI format
`build_messages(system_prompt, history, user_input, runtime_context)` SHALL return a list of dicts: system message first, then history messages, then user message last.

Before emitting the history portion, `build_messages` SHALL scan the `history` list from the tail toward the head for the most recent message with `metadata.is_compact_boundary == True`. If such a marker is found:

1. Messages BEFORE the boundary marker SHALL NOT be emitted to the downstream model (audit-only, kept in PG for replay).
2. The boundary marker itself SHALL NOT be emitted.
3. The summary message immediately preceding the boundary marker (identified by `metadata.is_compact_summary == True`) SHALL be emitted as a normal `{"role": "user", "content": "<summary>"}` entry (metadata stripped) so the model receives the summary as its effective first user turn.
4. All messages AFTER the boundary marker SHALL be emitted unchanged in order.

If no boundary marker is present, `build_messages` SHALL emit the full history as-is (backward compatibility with pre-change sessions).

When emitting any message that has a non-empty `metadata` dict, `build_messages` SHALL strip the `metadata` field before passing to the adapter — adapters expect plain OpenAI-format dicts and should never see the `metadata` key.

#### Scenario: Fresh conversation with no history
- **WHEN** build_messages is called with system_prompt="You are...", history=[], user_input="hello"
- **THEN** it returns `[{"role": "system", "content": "You are..."}, {"role": "user", "content": "hello"}]`

#### Scenario: Conversation with history
- **WHEN** build_messages is called with non-empty history list and no compact boundary marker
- **THEN** history messages appear between system and user messages in order

#### Scenario: Runtime context appended to system prompt
- **WHEN** build_messages is called with runtime_context={"current_time": "2026-04-07 15:00", "agent_id": "agent-1"}
- **THEN** the system message content SHALL end with a Runtime Context section containing those key-value pairs

#### Scenario: No runtime context
- **WHEN** build_messages is called with runtime_context=None
- **THEN** the system message content SHALL be the unmodified system_prompt

#### Scenario: History with compact boundary slices older messages
- **WHEN** build_messages is called with a history containing 50 pre-compact messages, then a summary message with `metadata.is_compact_summary=True`, then a boundary marker with `metadata.is_compact_boundary=True`, then 10 post-compact messages
- **THEN** the returned list SHALL contain: system message, summary-as-user-message, the 10 post-compact messages, then the final user input
- **AND** the 50 pre-compact messages SHALL NOT appear in the output
- **AND** the boundary marker itself SHALL NOT appear in the output

#### Scenario: Multiple compact boundaries, only the last one takes effect
- **WHEN** the history contains two compact cycles — an older boundary at index 20 and a newer boundary at index 60
- **THEN** only messages after index 60 plus the summary paired with the index-60 boundary SHALL be emitted
- **AND** messages 0..19, the older summary, and the older boundary SHALL NOT be emitted

#### Scenario: Metadata stripped before adapter
- **WHEN** an emitted history message originally had a `metadata` field
- **THEN** the dict returned by build_messages for that message SHALL NOT contain a `metadata` key
