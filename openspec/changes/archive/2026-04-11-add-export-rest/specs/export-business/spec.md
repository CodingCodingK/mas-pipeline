## ADDED Requirements

### Requirement: export_markdown extracts a completed run's final output as a downloadable artifact

`src.export.export_markdown(run_id: str) -> ExportArtifact` SHALL fetch the `WorkflowRun` identified by `run_id`, validate that it is in a completed state with an exportable payload, and return an `ExportArtifact` dataclass whose `content` field is the run's persisted `final_output`.

The function SHALL NOT synthesize, reformat, or wrap the final output — it is returned byte-for-byte (as a Python `str`) from `WorkflowRun.metadata_['final_output']`.

#### Scenario: Happy path for a completed run

- **GIVEN** a WorkflowRun with `status='completed'`, `pipeline='blog_generation'`, `run_id='abcdef1234567890'`, and `metadata_={'final_output': '# Report\n\nhello'}`
- **WHEN** `export_markdown('abcdef1234567890')` is called
- **THEN** it SHALL return an `ExportArtifact` with `content='# Report\n\nhello'`, `content_type='text/markdown; charset=utf-8'`, `filename='blog_generation_abcdef12.md'`, and `display_filename='blog_generation_abcdef12.md'`

#### Scenario: display_filename preserves non-ASCII pipeline name

- **GIVEN** a completed run with `pipeline='博客生成'` and `run_id='abcdef1234567890'`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** the returned `ExportArtifact.filename` SHALL equal `'_____abcdef12.md'` (non-ASCII collapsed to `_`) AND `ExportArtifact.display_filename` SHALL equal `'博客生成_abcdef12.md'` (original name preserved, for use in the RFC 6266 `filename*` extended form)

#### Scenario: Returned ExportArtifact is a frozen dataclass

- **WHEN** an `ExportArtifact` instance has been returned
- **THEN** attempting to reassign `artifact.content = "other"` SHALL raise `FrozenInstanceError`

### Requirement: RunNotFoundError raised when run_id does not exist

When `get_run(run_id)` returns `None`, `export_markdown` SHALL raise `RunNotFoundError` without attempting to build an artifact.

#### Scenario: Unknown run_id

- **GIVEN** no WorkflowRun exists with run_id='missing'
- **WHEN** `export_markdown('missing')` is called
- **THEN** it SHALL raise `RunNotFoundError`

### Requirement: RunNotFinishedError raised when status is not 'completed'

`export_markdown` SHALL raise `RunNotFinishedError` for runs whose `status` is any value other than `'completed'` — including `'pending'`, `'running'`, `'paused'`, `'failed'`, and `'cancelled'`. The exception message SHALL include the actual current status so the caller can render it to the user.

#### Scenario: Running run cannot be exported

- **GIVEN** a WorkflowRun with `status='running'`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** it SHALL raise `RunNotFinishedError` AND the exception message SHALL contain the word 'running'

#### Scenario: Failed run cannot be exported

- **GIVEN** a WorkflowRun with `status='failed'` and `metadata_={'final_output': ''}`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** it SHALL raise `RunNotFinishedError` (not `NoFinalOutputError` — the status check runs first)

#### Scenario: Paused run cannot be exported

- **GIVEN** a WorkflowRun with `status='paused'`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** it SHALL raise `RunNotFinishedError`

### Requirement: NoFinalOutputError raised when completed run has no final_output

When the run is in `completed` status but `metadata_['final_output']` is missing, None, or empty string, `export_markdown` SHALL raise `NoFinalOutputError`.

#### Scenario: Completed run with empty final_output

- **GIVEN** a WorkflowRun with `status='completed'` and `metadata_={'final_output': ''}`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** it SHALL raise `NoFinalOutputError`

#### Scenario: Legacy run with empty metadata

- **GIVEN** a WorkflowRun with `status='completed'` and `metadata_={}` (pre-Change-1.5 data)
- **WHEN** `export_markdown(run_id)` is called
- **THEN** it SHALL raise `NoFinalOutputError`

#### Scenario: Final output key present but None

- **GIVEN** a WorkflowRun with `status='completed'` and `metadata_={'final_output': None}`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** it SHALL raise `NoFinalOutputError`

### Requirement: Filename derivation is deterministic and filesystem-safe

`export_markdown` SHALL build the artifact filename as `{sanitized_pipeline}_{run_id_short}.md`, where `sanitized_pipeline` is `WorkflowRun.pipeline` with every character not in `[A-Za-z0-9_-]` replaced by `_`, or the literal `"run"` if `WorkflowRun.pipeline` is None. `run_id_short` is the first 8 characters of `WorkflowRun.run_id`.

In parallel, `export_markdown` SHALL also set `ExportArtifact.display_filename` to `{pipeline}_{run_id_short}.md` using the **unsanitized** `WorkflowRun.pipeline` (or `"run"` if None). This gives the REST layer access to the original name so the RFC 6266 `filename*=UTF-8''...` extended form can percent-encode it.

#### Scenario: Pipeline name with special characters

- **GIVEN** a completed run with `pipeline='blog/test'` and `run_id='abcdef1234567890'`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** the returned `ExportArtifact.filename` SHALL equal `'blog_test_abcdef12.md'`

#### Scenario: Pipeline name is None

- **GIVEN** a completed run with `pipeline=None` and `run_id='abcdef1234567890'`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** the returned `ExportArtifact.filename` SHALL equal `'run_abcdef12.md'`

#### Scenario: Non-ASCII pipeline name is collapsed

- **GIVEN** a completed run with `pipeline='博客_test'`
- **WHEN** `export_markdown(run_id)` is called
- **THEN** each non-ASCII character in the pipeline name SHALL be replaced by `_` in the resulting filename

### Requirement: Exception classes share a common base

`ExportError` SHALL be the base class for all exceptions raised by `src.export.exporter`, and `RunNotFoundError`, `RunNotFinishedError`, and `NoFinalOutputError` SHALL all inherit from it. This allows a single `except ExportError:` to catch any exporter-specific failure.

#### Scenario: Base-class catch

- **WHEN** a caller wraps `export_markdown(run_id)` in `try: ... except ExportError as e: ...`
- **THEN** it SHALL catch `RunNotFoundError`, `RunNotFinishedError`, and `NoFinalOutputError` alike
