# gateway-resume Specification

## Purpose
TBD - created by archiving change pipeline-interrupt. Update Purpose after archive.
## Requirements
### Requirement: /resume command recognition
Gateway SHALL recognize messages starting with `/resume` as a resume command, not as regular chat input.

#### Scenario: Exact /resume command
- **WHEN** a user sends "/resume"
- **THEN** Gateway SHALL treat it as a resume command, NOT pass it to the chat agent

#### Scenario: /resume with run_id
- **WHEN** a user sends "/resume run-abc"
- **THEN** Gateway SHALL attempt to resume the pipeline with run_id="run-abc"

#### Scenario: Regular message not intercepted
- **WHEN** a user sends "please resume the task"
- **THEN** Gateway SHALL treat it as normal chat input (no intent detection)

### Requirement: /resume queries paused pipelines for session
When `/resume` is sent without a run_id, Gateway SHALL query all paused pipeline runs associated with the current session/project.

#### Scenario: Single paused run auto-resumes
- **WHEN** the session has exactly one paused pipeline run
- **THEN** Gateway SHALL automatically resume that run and notify the user

#### Scenario: Multiple paused runs lists options
- **WHEN** the session has multiple paused pipeline runs
- **THEN** Gateway SHALL reply with a numbered list of paused runs (run_id, pipeline name, paused node) and ask the user to specify

#### Scenario: No paused runs
- **WHEN** the session has no paused pipeline runs
- **THEN** Gateway SHALL reply with "没有暂停的 pipeline" or equivalent message

### Requirement: /resume triggers resume_pipeline
After identifying the target run, Gateway SHALL call `resume_pipeline(run_id, feedback)` where feedback is any text after `/resume <run_id>`.

#### Scenario: Resume with feedback text
- **WHEN** user sends "/resume run-abc approved, proceed"
- **THEN** Gateway SHALL call resume_pipeline("run-abc", "approved, proceed")

#### Scenario: Resume result sent back to channel
- **WHEN** resume_pipeline completes
- **THEN** Gateway SHALL send the pipeline result or continuation status back to the user's channel

### Requirement: /resume only affects pipeline path
The `/resume` command SHALL only interact with the pipeline execution path. It SHALL NOT affect Coordinator autonomous mode or Gateway chat sessions.

#### Scenario: /resume does not trigger coordinator
- **WHEN** /resume is processed
- **THEN** coordinator_loop SHALL NOT be invoked

#### Scenario: /resume does not create chat agent
- **WHEN** /resume is processed
- **THEN** Gateway SHALL NOT create a chat agent for this message

