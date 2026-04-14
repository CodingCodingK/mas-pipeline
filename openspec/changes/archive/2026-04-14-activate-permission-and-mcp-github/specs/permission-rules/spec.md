## MODIFIED Requirements

### Requirement: TOOL_CONTENT_FIELD maps tool names to their matchable parameter
`TOOL_CONTENT_FIELD` SHALL be a `dict[str, str]` mapping tool name to the parameter field name used for pattern matching. It SHALL contain at least: shell→command, write_file→file_path, write→file_path, read_file→file_path, edit→file_path, web_search→query.

#### Scenario: Known tool field lookup
- **WHEN** looking up "shell" in TOOL_CONTENT_FIELD
- **THEN** it SHALL return "command"

#### Scenario: write_file field lookup
- **WHEN** looking up "write_file" in TOOL_CONTENT_FIELD
- **THEN** it SHALL return "file_path"

#### Scenario: Unknown tool has no field
- **WHEN** looking up "spawn_agent" in TOOL_CONTENT_FIELD
- **THEN** it SHALL not be present (KeyError or .get returns None)
