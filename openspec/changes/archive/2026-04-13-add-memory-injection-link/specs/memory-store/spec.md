## MODIFIED Requirements

### Requirement: Memory type classification
Each memory SHALL have a `type` field from a defined set: `"user"`, `"feedback"`, `"project"`, `"reference"`. The type is informational metadata that guides the writing agent's classification decision; it does not affect storage behavior. The set mirrors Claude Code's `memdir` taxonomy and replaces the previous `{fact, preference, context, instruction}` enum.

Semantic meaning of each type:
- `user` — durable facts about the user's role, expertise, and how they want to be helped
- `feedback` — guidance the user has given on how to approach work (corrections AND confirmations), including *why*
- `project` — ongoing work, goals, stakeholders, deadlines, decisions that are not derivable from files or git history
- `reference` — pointers to resources living outside this project (external systems, URLs, shared drives)

The old enum values are NOT accepted. `memory-store`'s `VALID_TYPES` constant SHALL be `{"user", "feedback", "project", "reference"}`.

#### Scenario: Valid types accepted
- **WHEN** `write_memory` is called with `type="user"`, `type="feedback"`, `type="project"`, or `type="reference"`
- **THEN** the memory is stored successfully

#### Scenario: Unknown type rejected
- **WHEN** `write_memory` is called with `type="fact"` (legacy) or any other value not in the new enum
- **THEN** it SHALL raise `ValueError` whose message lists the four valid types

#### Scenario: Zero-migration rename
- **WHEN** this change is deployed against a `memories` table that has been empty
- **THEN** no data migration SHALL be required and no rows SHALL need type rewriting
