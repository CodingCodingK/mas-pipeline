## ADDED Requirements

### Requirement: Coordinator role file defines the agent persona
`agents/coordinator.md` SHALL define the Coordinator Agent's role with frontmatter specifying tools and model_tier.

#### Scenario: Role file frontmatter
- **WHEN** agents/coordinator.md is loaded
- **THEN** frontmatter SHALL include tools: [spawn_agent]
- **AND** model_tier SHALL be "heavy" (coordination requires strong reasoning)

### Requirement: Coordinator has no execution tools
The Coordinator Agent SHALL NOT have access to execution tools (read_file, shell, write_file). It can only coordinate via spawn_agent.

#### Scenario: Tool access restriction
- **WHEN** a Coordinator Agent is created
- **THEN** its available tools SHALL be limited to spawn_agent
- **AND** it SHALL NOT have read_file, shell, or write_file

### Requirement: Role prompt defines coordination workflow
The Coordinator prompt SHALL instruct the agent to follow a task workflow: analyze the request → plan tasks → spawn agents → wait for results → synthesize output.

#### Scenario: Coordination behavior
- **WHEN** the Coordinator Agent processes a user request
- **THEN** it SHALL break the request into sub-tasks, spawn agents for each, and synthesize results once all complete

### Requirement: Role prompt explains notification mechanism
The prompt SHALL explain that worker results arrive as `<task-notification>` XML messages, not via tool calls.

#### Scenario: Notification awareness
- **WHEN** the Coordinator receives a `<task-notification>` message
- **THEN** it SHALL parse the notification to understand which agent completed and what the result is

### Requirement: Role prompt includes parallel strategy guidance
The prompt SHALL instruct the Coordinator to spawn independent tasks in parallel and sequence dependent tasks.

#### Scenario: Independent tasks
- **WHEN** the Coordinator identifies tasks with no dependencies between them
- **THEN** it SHALL spawn them simultaneously (multiple spawn_agent calls in one turn)

#### Scenario: Dependent tasks
- **WHEN** task B depends on the output of task A
- **THEN** the Coordinator SHALL spawn task A first, wait for completion, then spawn task B

### Requirement: Role prompt includes prompt writing guidance
The prompt SHALL instruct the Coordinator to write self-contained prompts for sub-agents: include all necessary context, avoid references like "based on your findings".

#### Scenario: Sub-agent prompt quality
- **WHEN** the Coordinator writes a prompt for a sub-agent
- **THEN** the prompt SHALL be self-contained with all relevant context embedded
- **AND** it SHALL NOT use phrases like "based on your findings" or "from the previous analysis"

### Requirement: Role prompt includes synthesis guidance
The prompt SHALL instruct the Coordinator to synthesize results from all sub-agents into a coherent final output after all tasks complete.

#### Scenario: Result synthesis
- **WHEN** all sub-agent tasks are completed
- **THEN** the Coordinator SHALL produce a unified output that synthesizes all sub-agent results
- **AND** it SHALL NOT simply concatenate results
