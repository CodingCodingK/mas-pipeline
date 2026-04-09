## ADDED Requirements

### Requirement: SkillDefinition dataclass holds parsed skill metadata and content
`SkillDefinition` SHALL be a dataclass with fields: name (str), description (str), when_to_use (str), context (str: "inline"|"fork"), model_tier (str, default "inherit"), tools (list[str]), always (bool, default False), arguments (str), content (str).

#### Scenario: Construct a fork skill
- **WHEN** SkillDefinition is created with name="research", context="fork", tools=["web_search"], always=False, content="Research $ARGUMENTS"
- **THEN** all fields SHALL be accessible with the provided values

#### Scenario: Default values
- **WHEN** SkillDefinition is created with only name and content
- **THEN** context SHALL be "inline", model_tier SHALL be "inherit", tools SHALL be [], always SHALL be False, arguments SHALL be "", description SHALL be "", when_to_use SHALL be ""

### Requirement: load_skill parses a single skill markdown file
`load_skill(path)` SHALL parse a `.md` file with YAML frontmatter and body into a SkillDefinition. The name SHALL default to the filename without extension if not specified in frontmatter.

#### Scenario: Parse skill with full frontmatter
- **GIVEN** a file `skills/research.md` with frontmatter containing name, description, context, tools, always, arguments
- **WHEN** load_skill is called with that path
- **THEN** it SHALL return a SkillDefinition with all fields populated from frontmatter and content from the body

#### Scenario: Parse skill with minimal frontmatter
- **GIVEN** a file `skills/summarize.md` with only `description: "Summarize text"` in frontmatter
- **WHEN** load_skill is called
- **THEN** name SHALL be "summarize" (from filename), context SHALL be "inline", always SHALL be False

#### Scenario: File without frontmatter
- **GIVEN** a `.md` file with no YAML frontmatter
- **WHEN** load_skill is called
- **THEN** name SHALL be derived from filename, content SHALL be the entire file text, all other fields SHALL use defaults

#### Scenario: Invalid file
- **WHEN** load_skill is called with a non-existent path
- **THEN** it SHALL raise FileNotFoundError

### Requirement: load_skills scans a directory for all skill files
`load_skills(skills_dir)` SHALL scan the directory for all `.md` files and return a `dict[str, SkillDefinition]` keyed by skill name. If skills_dir is None, it SHALL use the default `skills/` directory relative to project root.

#### Scenario: Load multiple skills
- **GIVEN** a directory with `research.md` and `summarize.md`
- **WHEN** load_skills is called
- **THEN** it SHALL return a dict with keys "research" and "summarize"

#### Scenario: Empty directory
- **GIVEN** a directory with no `.md` files
- **WHEN** load_skills is called
- **THEN** it SHALL return an empty dict

#### Scenario: Non-existent directory
- **WHEN** load_skills is called with a directory that does not exist
- **THEN** it SHALL return an empty dict (not raise)
