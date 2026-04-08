## MODIFIED Requirements

### Requirement: Global tool pool includes web_search
`get_all_tools()` SHALL return all built-in tool instances including WebSearchTool. The full pool SHALL be: read_file, shell, spawn_agent, web_search.

#### Scenario: get_all_tools includes web_search
- **WHEN** get_all_tools() is called
- **THEN** the returned dict SHALL contain a key "web_search" mapped to a WebSearchTool instance

#### Scenario: Agent with web_search in role whitelist
- **WHEN** create_agent is called with a role whose frontmatter includes tools: [web_search]
- **THEN** the agent's ToolRegistry SHALL contain WebSearchTool
