## MODIFIED Requirements

### Requirement: Global tool pool includes web_search
`get_all_tools()` SHALL return all built-in tool instances including WebSearchTool, MemoryReadTool, MemoryWriteTool, SearchDocsTool, and WriteFileTool. The full pool SHALL be: read_file, write_file, shell, spawn_agent, web_search, memory_read, memory_write, search_docs.

#### Scenario: get_all_tools includes web_search
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "web_search" mapped to a WebSearchTool instance

#### Scenario: get_all_tools includes memory tools
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain keys "memory_read" and "memory_write" mapped to their respective tool instances

#### Scenario: get_all_tools includes search_docs
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "search_docs" mapped to a SearchDocsTool instance

#### Scenario: get_all_tools includes write_file
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "write_file" mapped to a WriteFileTool instance

#### Scenario: Total tool count
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL have exactly 8 entries

#### Scenario: Agent with web_search in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [web_search]
- **THEN** the agent's ToolRegistry SHALL contain WebSearchTool

#### Scenario: Agent with memory tools in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [memory_read, memory_write]
- **THEN** the agent's ToolRegistry SHALL contain both MemoryReadTool and MemoryWriteTool

#### Scenario: Agent with write_file in role whitelist
- **GIVEN** agents/writer.md has tools: [read_file, write_file]
- **WHEN** create_agent is called for role writer
- **THEN** the agent's ToolRegistry SHALL contain WriteFileTool

## ADDED Requirements

### Requirement: writer / assistant / general roles have write_file in their tool frontmatter
The role files `agents/writer.md`, `agents/assistant.md`, and `agents/general.md` SHALL each include `write_file` in their `tools:` frontmatter list. Other pipeline worker roles (analyzer, exam_generator, exam_reviewer, reviewer, parser, coordinator, researcher) SHALL NOT have `write_file` in their tools list.

#### Scenario: Writer role has write_file
- **WHEN** `agents/writer.md` frontmatter is parsed
- **THEN** its `tools` list SHALL contain `"write_file"`

#### Scenario: Assistant role has write_file
- **WHEN** `agents/assistant.md` frontmatter is parsed
- **THEN** its `tools` list SHALL contain `"write_file"`

#### Scenario: General role has write_file
- **WHEN** `agents/general.md` frontmatter is parsed
- **THEN** its `tools` list SHALL contain `"write_file"`

#### Scenario: Parser role does not have write_file
- **WHEN** `agents/parser.md` frontmatter is parsed
- **THEN** its `tools` list SHALL NOT contain `"write_file"`
