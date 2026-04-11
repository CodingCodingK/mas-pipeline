## MODIFIED Requirements

### Requirement: embed produces vectors for text inputs
`embed(texts, *, progress_callback=None)` SHALL call the configured embedding API and return a list of float vectors, one per input text. If `progress_callback` is provided, it SHALL be awaited after each batch (every 100 texts) with `{"event": "embedding_progress", "done": <int>, "total": <int>}`.

#### Scenario: Single text embedding
- **WHEN** embed is called with `["Hello world"]`
- **THEN** it SHALL return a list containing one vector of length matching `settings.embedding.dimensions`

#### Scenario: Batch embedding
- **WHEN** embed is called with 150 texts
- **THEN** it SHALL split into batches of at most 100, call the API for each batch, and return 150 vectors concatenated in order

#### Scenario: Empty input
- **WHEN** embed is called with an empty list
- **THEN** it SHALL return an empty list without making any API call

#### Scenario: Progress callback receives per-batch ticks
- **WHEN** embed is called with 250 texts and a `progress_callback`
- **THEN** the callback SHALL be awaited 3 times with `done` values `100`, `200`, `250` and `total=250`

#### Scenario: No callback is backward compatible
- **WHEN** embed is called without a `progress_callback` argument
- **THEN** it SHALL behave identically to the prior version (no callbacks invoked)
