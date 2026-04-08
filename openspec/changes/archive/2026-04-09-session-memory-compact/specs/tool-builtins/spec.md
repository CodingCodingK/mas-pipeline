## MODIFIED Requirements

### Requirement: Global tool pool includes web_search
`get_all_tools()` SHALL return all built-in tool instances including WebSearchTool, MemoryReadTool, and MemoryWriteTool. The full pool SHALL be: read_file, shell, spawn_agent, web_search, memory_read, memory_write.

#### Scenario: get_all_tools includes memory tools
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain keys "memory_read" and "memory_write" mapped to their respective tool instances

#### Scenario: Total tool count
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL have exactly 6 entries

#### Scenario: Agent with memory tools in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [memory_read, memory_write]
- **THEN** the agent's ToolRegistry SHALL contain both memory tools
