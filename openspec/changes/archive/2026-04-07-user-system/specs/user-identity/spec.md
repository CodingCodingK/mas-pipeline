## ADDED Requirements

### Requirement: User dataclass represents a database user record
`User` SHALL be a dataclass with fields: `id: int`, `name: str`, `email: str | None`, `config: dict`, `created_at: datetime`. Fields SHALL match the `users` table schema.

#### Scenario: User fields match database columns
- **WHEN** a User instance is created from a database row
- **THEN** all fields (id, name, email, config, created_at) SHALL be populated from the corresponding columns

### Requirement: get_current_user returns the default user from database
`get_current_user()` SHALL read the `default_user.name` from settings, query the `users` table by name, and return a `User` instance.

#### Scenario: Default user exists in database
- **WHEN** `get_current_user()` is called and the default user name from settings matches a record in the `users` table
- **THEN** it SHALL return a `User` instance with the matching database record

#### Scenario: Default user not found in database
- **WHEN** `get_current_user()` is called and no user with the configured name exists in the `users` table
- **THEN** it SHALL raise a `ValueError` with a message indicating the user was not found and suggesting to run init_db.sql

#### Scenario: Database not available
- **WHEN** `get_current_user()` is called and the database connection fails
- **THEN** the database exception SHALL propagate to the caller (no silent fallback)

### Requirement: get_current_user caches the result
`get_current_user()` SHALL cache the result after the first successful database query. Subsequent calls SHALL return the cached value without querying the database.

#### Scenario: Multiple calls return same instance
- **WHEN** `get_current_user()` is called twice
- **THEN** only one database query SHALL be executed, and both calls SHALL return the same User instance
