## MODIFIED Requirements

### Requirement: Global tool pool includes web_search
`get_all_tools()` SHALL return all built-in tool instances including WebSearchTool, MemoryReadTool, MemoryWriteTool, and SearchDocsTool. The full pool SHALL be: read_file, shell, spawn_agent, web_search, memory_read, memory_write, search_docs.

#### Scenario: get_all_tools includes web_search
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "web_search" mapped to a WebSearchTool instance

#### Scenario: get_all_tools includes memory tools
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain keys "memory_read" and "memory_write" mapped to their respective tool instances

#### Scenario: get_all_tools includes search_docs
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "search_docs" mapped to a SearchDocsTool instance

#### Scenario: Total tool count
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL have exactly 7 entries

#### Scenario: Agent with search_docs in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [search_docs]
- **THEN** the agent's ToolRegistry SHALL contain SearchDocsTool
