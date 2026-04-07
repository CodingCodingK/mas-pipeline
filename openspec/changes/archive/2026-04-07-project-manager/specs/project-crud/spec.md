## ADDED Requirements

### Requirement: Project dataclass represents a database project record
`Project` SHALL be a dataclass with fields matching the `projects` table: `id: int`, `user_id: int`, `name: str`, `description: str | None`, `pipeline: str`, `config: dict`, `status: str`, `created_at: datetime`, `updated_at: datetime`.

#### Scenario: Project fields match database columns
- **WHEN** a Project instance is created from a database row
- **THEN** all fields SHALL be populated from the corresponding columns

### Requirement: create_project inserts a new project and creates uploads directory
`create_project(user_id, name, pipeline, description, config)` SHALL insert a row into the `projects` table and create the directory `uploads/{project_id}/`.

#### Scenario: Successful project creation
- **WHEN** create_project is called with valid parameters
- **THEN** a new row SHALL be inserted into `projects` with the given user_id, name, pipeline, description, config, and status='active'
- **AND** the directory `uploads/{project_id}/` SHALL be created
- **AND** a Project instance SHALL be returned with the generated id

#### Scenario: Uploads directory already exists
- **WHEN** create_project is called and `uploads/{project_id}/` already exists
- **THEN** no error SHALL be raised (exist_ok behavior)

### Requirement: get_project returns a single project by id
`get_project(project_id, user_id)` SHALL query the `projects` table by id and user_id and return a Project instance.

#### Scenario: Project exists
- **WHEN** get_project is called with a valid project_id belonging to the user
- **THEN** it SHALL return the matching Project instance

#### Scenario: Project not found
- **WHEN** get_project is called with a non-existent project_id or wrong user_id
- **THEN** it SHALL return None

### Requirement: list_projects returns active projects for a user
`list_projects(user_id)` SHALL return all projects with status='active' for the given user_id, ordered by created_at descending.

#### Scenario: User has active projects
- **WHEN** list_projects is called for a user with active projects
- **THEN** it SHALL return all active projects ordered by created_at descending

#### Scenario: User has no active projects
- **WHEN** list_projects is called for a user with no active projects
- **THEN** it SHALL return an empty list

### Requirement: update_project modifies project fields
`update_project(project_id, user_id, **kwargs)` SHALL update the specified fields and set updated_at to NOW().

#### Scenario: Update name and description
- **WHEN** update_project is called with name="new name" and description="new desc"
- **THEN** the project row SHALL have the updated values and a fresh updated_at

#### Scenario: Update non-existent project
- **WHEN** update_project is called with a non-existent project_id
- **THEN** it SHALL return None

### Requirement: archive_project soft-deletes a project
`archive_project(project_id, user_id)` SHALL set the project's status to 'archived' and update updated_at.

#### Scenario: Archive existing project
- **WHEN** archive_project is called for an active project
- **THEN** status SHALL be set to 'archived' and updated_at SHALL be refreshed

#### Scenario: Archived project excluded from list
- **WHEN** a project is archived and list_projects is called
- **THEN** the archived project SHALL NOT appear in the results
