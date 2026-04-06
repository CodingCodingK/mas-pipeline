## ADDED Requirements

### Requirement: Route model name to provider by prefix
The system SHALL maintain a prefix-to-provider mapping and resolve any model name to its provider by matching the longest prefix. Unrecognized model names SHALL raise an error.

#### Scenario: Known prefix routes correctly
- **WHEN** `route("gpt-4o-mini")` is called
- **THEN** it returns an `OpenAICompatAdapter` configured with OpenAI's api_key and api_base

#### Scenario: Gemini routes correctly
- **WHEN** `route("gemini-2.5-pro")` is called
- **THEN** it returns an `OpenAICompatAdapter` configured with Gemini's api_key and api_base

#### Scenario: DeepSeek routes correctly
- **WHEN** `route("deepseek-chat")` is called
- **THEN** it returns an `OpenAICompatAdapter` configured with DeepSeek's api_key and api_base

#### Scenario: Unknown model raises error
- **WHEN** `route("unknown-model-xyz")` is called
- **THEN** the system raises a `ValueError` with a message indicating the model name could not be matched to any provider

### Requirement: Router reads provider config from Settings
The system SHALL read `api_key` and `api_base` for each provider from `Settings.providers` (loaded via `get_settings()`).

#### Scenario: Provider config loaded
- **WHEN** the Router initializes
- **THEN** it reads provider configurations from `get_settings().providers`

#### Scenario: Missing provider config
- **WHEN** a model name maps to a provider not present in Settings.providers
- **THEN** the system raises an error indicating the provider is not configured

### Requirement: Route by model tier
The system SHALL support routing by tier name (`strong`, `medium`, `light`), resolving to the model name configured in `Settings.models`.

#### Scenario: Tier resolves to model
- **WHEN** `route("strong")` is called and `Settings.models.strong` is `gemini-2.5-pro`
- **THEN** it returns the same adapter as `route("gemini-2.5-pro")`

#### Scenario: Unknown tier
- **WHEN** `route("unknown-tier")` is called and it matches neither a tier name nor a model prefix
- **THEN** the system raises a `ValueError`
