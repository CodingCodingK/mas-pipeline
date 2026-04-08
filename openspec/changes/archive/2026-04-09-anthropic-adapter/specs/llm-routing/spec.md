## MODIFIED Requirements

### Requirement: Route model name to provider by prefix
The system SHALL maintain a prefix-to-provider mapping and resolve any model name to its provider by matching the longest prefix. Unrecognized model names SHALL raise an error. When the provider is `"anthropic"`, the system SHALL return an `AnthropicAdapter` instance; for all other providers, it SHALL return an `OpenAICompatAdapter` instance.

#### Scenario: Known prefix routes correctly
- **WHEN** `route("gpt-4o-mini")` is called
- **THEN** it returns an `OpenAICompatAdapter` configured with OpenAI's api_key and api_base

#### Scenario: Gemini routes correctly
- **WHEN** `route("gemini-2.5-pro")` is called
- **THEN** it returns an `OpenAICompatAdapter` configured with Gemini's api_key and api_base

#### Scenario: DeepSeek routes correctly
- **WHEN** `route("deepseek-chat")` is called
- **THEN** it returns an `OpenAICompatAdapter` configured with DeepSeek's api_key and api_base

#### Scenario: Claude routes to AnthropicAdapter
- **WHEN** `route("claude-sonnet-4-6")` is called
- **THEN** it returns an `AnthropicAdapter` configured with Anthropic's api_key and api_base

#### Scenario: Claude tier routes to AnthropicAdapter
- **WHEN** `route("medium")` is called and `Settings.models.medium` is `claude-sonnet-4-6`
- **THEN** it returns an `AnthropicAdapter` configured with Anthropic's api_key and api_base

#### Scenario: Unknown model raises error
- **WHEN** `route("unknown-model-xyz")` is called
- **THEN** the system raises a `ValueError` with a message indicating the model name could not be matched to any provider
