## MODIFIED Requirements

### Requirement: LLMAdapter defines async call interface
The system SHALL define an abstract base class `LLMAdapter` with two async methods:
- `call(messages, tools=None, **kwargs) -> LLMResponse` (existing, unchanged)
- `call_stream(messages, tools=None, **kwargs) -> AsyncIterator[StreamEvent]` (new)

Both methods SHALL be abstract. Subclasses MUST implement both.

#### Scenario: Subclass must implement call
- **WHEN** a subclass of `LLMAdapter` does not implement `call()`
- **THEN** instantiation raises `TypeError`

#### Scenario: Subclass must implement call_stream
- **WHEN** a subclass of `LLMAdapter` does not implement `call_stream()`
- **THEN** instantiation raises `TypeError`

#### Scenario: call() behavior unchanged
- **WHEN** `call()` is invoked
- **THEN** it SHALL return a complete `LLMResponse` object, identical to pre-streaming behavior
