## ADDED Requirements

### Requirement: chunk_text splits text into overlapping chunks
`chunk_text(text, chunk_size=800, overlap=100)` SHALL split text into chunks with metadata. Split priority: section headers (`\n## `) > paragraph breaks (`\n\n`) > character limit hard cut.

#### Scenario: Short text fits in one chunk
- **WHEN** chunk_text is called with text shorter than chunk_size
- **THEN** it SHALL return a single Chunk with the full text and chunk_index=0

#### Scenario: Long text split at paragraphs
- **WHEN** chunk_text is called with text containing paragraph breaks
- **THEN** it SHALL split at paragraph boundaries, each chunk <= chunk_size characters

#### Scenario: Overlap between adjacent chunks
- **WHEN** chunk_text produces multiple chunks
- **THEN** adjacent chunks SHALL share approximately `overlap` characters at their boundaries

#### Scenario: Chunks carry metadata
- **WHEN** chunk_text produces chunks
- **THEN** each Chunk SHALL have a `chunk_index` field (0-based sequential)

### Requirement: Chunk dataclass holds content and metadata
`Chunk` SHALL be a dataclass with `content` (str) and `metadata` (dict) fields.

#### Scenario: Chunk construction
- **WHEN** a Chunk is created with content and metadata
- **THEN** both fields are accessible as attributes
