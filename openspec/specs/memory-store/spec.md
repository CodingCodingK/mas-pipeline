## Purpose
Project-scoped long-term memory backed by the `memories` PG table. Provides CRUD, type classification, LLM-driven relevance selection, and the ORM model used by the chat agent's Path A/B memory recall.
## Requirements
### Requirement: Memory CRUD operations
The system SHALL provide project-scoped memory CRUD backed by the `memories` PG table.

- `write_memory(project_id, type, name, description, content) -> Memory` — inserts new row, returns ORM instance
- `update_memory(memory_id, **kwargs)` — updates content/description/name fields, sets `updated_at`
- `delete_memory(memory_id)` — hard-deletes the row
- `list_memories(project_id) -> list[Memory]` — returns all memories for project (id, type, name, description only; content excluded for lightweight listing)
- `get_memory(memory_id) -> Memory` — returns full memory including content

#### Scenario: Write and list
- **WHEN** `write_memory(project_id=1, type="fact", name="User prefers dark mode", description="UI preference", content="User stated they prefer dark mode on 2026-04-08")` is called
- **THEN** a row is inserted and `list_memories(1)` includes a Memory with `name="User prefers dark mode"`

#### Scenario: Update memory content
- **WHEN** `update_memory(memory_id, content="Updated preference")` is called
- **THEN** `get_memory(memory_id).content` SHALL return `"Updated preference"` and `updated_at` SHALL be refreshed

#### Scenario: Delete memory
- **WHEN** `delete_memory(memory_id)` is called
- **THEN** the memory SHALL no longer appear in `list_memories` and `get_memory` SHALL raise `MemoryNotFoundError`

#### Scenario: List returns lightweight records
- **WHEN** `list_memories(project_id)` is called
- **THEN** each returned record SHALL include `id`, `type`, `name`, `description` but content MAY be omitted for efficiency

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

### Requirement: Memory relevance selection via LLM
`select_relevant(project_id, query, limit=5) -> list[Memory]` SHALL determine which memories are relevant to a given query using LLM judgment.

1. Load all memories for the project via `list_memories` (name + description only)
2. If no memories exist, return empty list
3. If memories exist, call light-tier LLM with a prompt containing the query and the list of memory names/descriptions
4. LLM returns a JSON array of memory IDs ranked by relevance
5. Fetch full content for top-`limit` IDs via `get_memory`
6. Return the list of full Memory objects

#### Scenario: Relevant memories selected
- **WHEN** project has 10 memories and `select_relevant(project_id, "What UI theme does the user prefer?", limit=3)` is called
- **THEN** the LLM evaluates all 10 memory summaries and returns up to 3 most relevant full Memory objects

#### Scenario: No memories in project
- **WHEN** `select_relevant(project_id, "anything")` is called on a project with no memories
- **THEN** it SHALL return an empty list without calling the LLM

#### Scenario: LLM returns fewer than limit
- **WHEN** LLM judges only 2 memories as relevant but limit=5
- **THEN** only 2 Memory objects SHALL be returned

### Requirement: Memory ORM model
The system SHALL define a `Memory` SQLAlchemy ORM model in `src/models.py` mapping to the existing `memories` table.

#### Scenario: Memory model fields
- **WHEN** Memory model is inspected
- **THEN** it SHALL have fields: `id` (int PK), `project_id` (int FK), `user_id` (int FK nullable), `scope` (str), `type` (str), `name` (str), `description` (str), `content` (str), `created_at`, `updated_at`

