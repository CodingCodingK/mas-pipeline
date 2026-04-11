## ADDED Requirements

### Requirement: Agent loop emits llm_call telemetry event after each LLM invocation
After each successful or failed LLM call in `agent_loop`, the system SHALL call `telemetry_collector.record_llm_call(...)` with the provider, model, token counts from `LLMResponse.usage`, measured latency, and finish reason.

Emission SHALL happen after the LLM response is received (or after the exception is raised in failure cases — failure path emits both a `llm_call` event with `finish_reason='error'` and a separate `error` event with `source='llm'`).

Emission SHALL NOT block the agent loop: the collector's `record_llm_call` is a synchronous queue append that returns in O(1).

Emission SHALL be a no-op when `telemetry.enabled=False`.

#### Scenario: Successful LLM call emits event
- **WHEN** `agent_loop` completes one LLM invocation with a valid response
- **THEN** exactly one `llm_call` event SHALL be emitted with tokens from `response.usage`, `latency_ms` measured from pre-call to post-call, and `finish_reason` from the response

#### Scenario: Failed LLM call emits both llm_call and error events
- **WHEN** an LLM invocation raises an exception (rate limit, network error, etc.)
- **THEN** one `llm_call` event SHALL be emitted with `finish_reason='error'` and best-effort token counts (may be 0)
- **AND** one `error` event SHALL be emitted with `source='llm'`, `error_type` set to the exception class, and the stacktrace hash

#### Scenario: Telemetry disabled path adds zero latency
- **WHEN** `telemetry.enabled=False` and an LLM call completes
- **THEN** no event SHALL be queued
- **AND** the agent loop SHALL proceed with sub-microsecond overhead from the bool check
