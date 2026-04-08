## ADDED Requirements

### Requirement: blog_generation pipeline YAML defines a 3-node linear pipeline
`pipelines/blog_generation.yaml` SHALL define a pipeline with 3 nodes: researcher → writer → reviewer, using dedicated role files.

#### Scenario: Pipeline structure
- **WHEN** blog_generation.yaml is loaded by load_pipeline()
- **THEN** it SHALL have 3 nodes named "researcher", "writer", "reviewer"
- **AND** dependencies SHALL be: writer depends on researcher, reviewer depends on writer

#### Scenario: Each node uses dedicated role
- **WHEN** nodes are inspected
- **THEN** researcher node SHALL have role="researcher"
- **AND** writer node SHALL have role="writer"
- **AND** reviewer node SHALL have role="reviewer"

### Requirement: researcher role searches and compiles research
`agents/researcher.md` SHALL define a role with tools [web_search, read_file] and model_tier medium. The prompt SHALL instruct the agent to search for information and produce a structured research report.

#### Scenario: Researcher output
- **WHEN** researcher node receives user_input "写一篇关于 RAG 优化的技术博客"
- **THEN** it SHALL use web_search to find relevant information
- **AND** produce a research report with key findings, sources, and data points

### Requirement: writer role drafts a blog post from research
`agents/writer.md` SHALL define a role with tools [read_file] and model_tier medium. The prompt SHALL instruct the agent to write a complete Markdown blog post based on the upstream research.

#### Scenario: Writer output
- **WHEN** writer node receives research report as input
- **THEN** it SHALL produce a complete Markdown blog post with title, sections, and conclusion

### Requirement: reviewer role polishes the draft into final output
`agents/reviewer.md` SHALL define a role with tools [] (no tools) and model_tier medium. The prompt SHALL instruct the agent to review, correct, and polish the draft.

#### Scenario: Reviewer output
- **WHEN** reviewer node receives a draft blog post
- **THEN** it SHALL output a polished final blog post in Markdown format
- **AND** fix grammar, structure, and clarity issues

### Requirement: blog_generation pipeline is accessible via run_coordinator
When a Project has pipeline="blog_generation", `run_coordinator` SHALL route to `execute_pipeline("blog_generation", ...)`.

#### Scenario: End-to-end execution
- **WHEN** run_coordinator is called with a project whose pipeline="blog_generation"
- **AND** user_input is "写一篇关于 RAG 优化的技术博客"
- **THEN** it SHALL execute the 3-node pipeline and return a CoordinatorResult with mode="pipeline"
