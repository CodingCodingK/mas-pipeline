## ADDED Requirements

### Requirement: courseware_exam pipeline YAML defines a 4-node linear pipeline
`pipelines/courseware_exam.yaml` SHALL define a pipeline with 4 nodes: parser → analyzer → exam_generator → exam_reviewer, using dedicated role files.

#### Scenario: Pipeline structure
- **WHEN** courseware_exam.yaml is loaded by load_pipeline()
- **THEN** it SHALL have 4 nodes named "parser", "analyzer", "exam_generator", "exam_reviewer"
- **AND** pipeline name SHALL be "courseware_exam"

#### Scenario: Node roles match names
- **WHEN** nodes are inspected
- **THEN** each node's role SHALL match its name (parser→parser, analyzer→analyzer, etc.)

#### Scenario: Output names
- **WHEN** nodes are inspected
- **THEN** outputs SHALL be: parsed_content, knowledge_points, exam_draft, final_exam

### Requirement: Dependency chain is strictly linear
The pipeline SHALL have a linear dependency chain: analyzer depends on parser, exam_generator depends on analyzer, exam_reviewer depends on exam_generator.

#### Scenario: Dependency inference
- **WHEN** load_pipeline() builds the dependency graph
- **THEN** parser SHALL have no dependencies (entry node)
- **AND** analyzer SHALL depend on parser
- **AND** exam_generator SHALL depend on analyzer
- **AND** exam_reviewer SHALL depend on exam_generator

### Requirement: parser role uses strong tier and read_file
`agents/parser.md` SHALL define a role with model_tier "strong" and tools [read_file]. The prompt SHALL instruct the agent to parse courseware content, extracting text structure, key concepts, and noting any visual elements (charts, diagrams, formulas).

#### Scenario: Parser role metadata
- **WHEN** parser.md frontmatter is parsed
- **THEN** model_tier SHALL be "strong"
- **AND** tools SHALL be ["read_file"]

#### Scenario: Parser prompt content
- **WHEN** parser.md body is read
- **THEN** it SHALL contain instructions for courseware content parsing
- **AND** body length SHALL exceed 50 characters

### Requirement: analyzer role extracts knowledge points
`agents/analyzer.md` SHALL define a role with model_tier "medium" and tools []. The prompt SHALL instruct the agent to analyze parsed courseware content and produce a structured list of knowledge points with importance levels.

#### Scenario: Analyzer role metadata
- **WHEN** analyzer.md frontmatter is parsed
- **THEN** model_tier SHALL be "medium"
- **AND** tools SHALL be []

#### Scenario: Analyzer prompt content
- **WHEN** analyzer.md body is read
- **THEN** it SHALL contain instructions for knowledge point extraction
- **AND** body length SHALL exceed 50 characters

### Requirement: exam_generator role uses search_docs for RAG-grounded question generation
`agents/exam_generator.md` SHALL define a role with model_tier "medium" and tools [search_docs, read_file]. The prompt SHALL instruct the agent to generate exam questions grounded in the courseware content retrieved via search_docs.

#### Scenario: Exam generator role metadata
- **WHEN** exam_generator.md frontmatter is parsed
- **THEN** model_tier SHALL be "medium"
- **AND** tools SHALL be ["search_docs", "read_file"]

#### Scenario: Exam generator uses RAG
- **WHEN** exam_generator receives knowledge points as input
- **THEN** it SHALL use search_docs to retrieve relevant courseware content
- **AND** generate questions based on retrieved content, not LLM memory alone

### Requirement: exam_reviewer role reviews and polishes exam output
`agents/exam_reviewer.md` SHALL define a role with model_tier "medium" and tools []. The prompt SHALL instruct the agent to review exam questions for correctness, clarity, difficulty balance, and alignment with the knowledge points.

#### Scenario: Exam reviewer role metadata
- **WHEN** exam_reviewer.md frontmatter is parsed
- **THEN** model_tier SHALL be "medium"
- **AND** tools SHALL be []

#### Scenario: Exam reviewer prompt content
- **WHEN** exam_reviewer.md body is read
- **THEN** it SHALL contain instructions for exam quality review
- **AND** body length SHALL exceed 50 characters

### Requirement: courseware_exam pipeline is accessible via run_coordinator
When a Project has pipeline="courseware_exam", `run_coordinator` SHALL route to `execute_pipeline("courseware_exam", ...)`.

#### Scenario: End-to-end routing
- **WHEN** run_coordinator is called with a project whose pipeline="courseware_exam"
- **AND** user_input describes a courseware file to process
- **THEN** it SHALL execute the 4-node pipeline and return a CoordinatorResult with mode="pipeline"

### Requirement: All requested tools exist in global tool pool
Every tool referenced in courseware_exam role files SHALL exist in get_all_tools().

#### Scenario: Tool pool validation
- **WHEN** all 4 role files are parsed for their tools lists
- **THEN** every tool name SHALL be a key in the dict returned by get_all_tools()
