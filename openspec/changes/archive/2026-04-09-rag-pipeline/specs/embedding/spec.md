## ADDED Requirements

### Requirement: embed produces vectors for text inputs
`embed(texts)` SHALL call the configured embedding API and return a list of float vectors, one per input text.

#### Scenario: Single text embedding
- **WHEN** embed is called with `["Hello world"]`
- **THEN** it SHALL return a list containing one vector of length matching `settings.embedding.dimensions`

#### Scenario: Batch embedding
- **WHEN** embed is called with 150 texts
- **THEN** it SHALL split into batches of at most 100, call the API for each batch, and return 150 vectors concatenated in order

#### Scenario: Empty input
- **WHEN** embed is called with an empty list
- **THEN** it SHALL return an empty list without making any API call

### Requirement: Embedding uses configured model and provider
embed SHALL read `settings.embedding.model`, `settings.embedding.provider`, and `settings.embedding.dimensions` to configure API calls.

#### Scenario: OpenAI embedding provider
- **WHEN** settings.embedding.provider is "openai"
- **THEN** embed SHALL call the OpenAI-compatible embedding endpoint at `{provider.api_base}/embeddings`

#### Scenario: Dimensions match configuration
- **WHEN** embed returns vectors
- **THEN** each vector length SHALL equal `settings.embedding.dimensions`
