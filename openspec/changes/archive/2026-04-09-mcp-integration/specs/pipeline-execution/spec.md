## MODIFIED Requirements

### Requirement: execute_pipeline function signature
`execute_pipeline(pipeline_name: str, run_id: str, project_id: int, user_input: str, permission_mode: PermissionMode = PermissionMode.NORMAL)` SHALL load the pipeline YAML, create an MCPManager from settings.yaml mcp_servers config, start all MCP servers, execute all nodes (passing the MCPManager to each create_agent call), and return results. The MCPManager SHALL be shut down when the pipeline completes (success or failure). The function SHALL NOT create a WorkflowRun — the caller provides a valid run_id. It SHALL fire PipelineStart hook at the beginning and PipelineEnd hook at the end. The `permission_mode` parameter SHALL default to `PermissionMode.NORMAL` (this is the only place in the codebase with a default value for permission_mode).

#### Scenario: Successful execution
- **WHEN** execute_pipeline is called with a valid pipeline_name and run_id
- **THEN** it SHALL load the pipeline, start MCP servers, execute all nodes, shut down MCP servers, and return a PipelineResult with status='completed'

#### Scenario: Pipeline YAML not found
- **WHEN** pipeline_name does not correspond to a file in the pipelines directory
- **THEN** it SHALL raise FileNotFoundError

#### Scenario: PipelineStart hook fires at beginning
- **WHEN** execute_pipeline is called
- **THEN** a PipelineStart hook event SHALL fire with payload containing pipeline_name, run_id, project_id, user_input before any node execution begins

#### Scenario: PipelineEnd hook fires on completion
- **WHEN** pipeline execution finishes (success or failure)
- **THEN** a PipelineEnd hook event SHALL fire with payload containing pipeline_name, run_id, status, error

#### Scenario: Permission mode passed to all nodes
- **WHEN** execute_pipeline is called with permission_mode=STRICT
- **THEN** every node's create_agent call SHALL receive permission_mode=STRICT

#### Scenario: Default permission mode is NORMAL
- **WHEN** execute_pipeline is called without specifying permission_mode
- **THEN** all nodes SHALL use PermissionMode.NORMAL

#### Scenario: MCP servers started before node execution
- **WHEN** execute_pipeline is called and settings.yaml has mcp_servers configured
- **THEN** MCPManager SHALL start all servers before any node begins execution

#### Scenario: MCP servers shut down after pipeline completes
- **WHEN** pipeline execution finishes (success or failure)
- **THEN** MCPManager.shutdown SHALL be called to close all MCP server connections

#### Scenario: MCPManager passed to node agents
- **WHEN** a node agent is created via create_agent during pipeline execution
- **THEN** the mcp_manager parameter SHALL be passed so the agent can access MCP tools

#### Scenario: No MCP servers configured
- **WHEN** settings.yaml has no mcp_servers field
- **THEN** execute_pipeline SHALL work normally without MCP (MCPManager starts with empty config)
