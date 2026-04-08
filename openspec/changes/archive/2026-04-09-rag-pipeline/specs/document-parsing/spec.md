## ADDED Requirements

### Requirement: Parse Markdown documents
`parse_markdown(file_path)` SHALL read a Markdown file and return a `ParseResult` containing the full text content.

#### Scenario: Valid Markdown file
- **WHEN** parse_markdown is called with a valid .md file
- **THEN** it SHALL return `ParseResult(text=<file content>, images=[])`

### Requirement: Parse PDF documents
`parse_pdf(file_path, images_dir)` SHALL use pymupdf4llm to convert PDF pages to Markdown text. For pages containing images, it SHALL additionally render the page as a PNG and save it to `images_dir`.

#### Scenario: Text-only PDF
- **WHEN** parse_pdf is called with a PDF containing only text
- **THEN** it SHALL return `ParseResult(text=<markdown text>, images=[])`

#### Scenario: PDF with images
- **WHEN** parse_pdf is called with a PDF containing images on pages 2 and 5
- **THEN** it SHALL return Markdown text for all pages, and `images` SHALL contain entries with `{page: int, path: str}` for the rendered page images

#### Scenario: PDF table preservation
- **WHEN** parse_pdf is called with a PDF containing tables
- **THEN** the returned Markdown text SHALL contain Markdown-formatted tables

### Requirement: Parse DOCX documents
`parse_docx(file_path, images_dir)` SHALL use python-docx to extract paragraph text and export embedded images.

#### Scenario: DOCX with text and images
- **WHEN** parse_docx is called with a DOCX file containing text and images
- **THEN** it SHALL return `ParseResult(text=<paragraphs joined>, images=[{name, path}])`

#### Scenario: DOCX text only
- **WHEN** parse_docx is called with a text-only DOCX
- **THEN** it SHALL return `ParseResult(text=<paragraphs>, images=[])`

### Requirement: parse_document dispatches by file type
`parse_document(file_path, file_type, images_dir)` SHALL dispatch to the correct parser based on file_type and return a `ParseResult`.

#### Scenario: Dispatch PDF
- **WHEN** parse_document is called with file_type="pdf"
- **THEN** it SHALL call parse_pdf and return its result

#### Scenario: Dispatch Markdown
- **WHEN** parse_document is called with file_type="md"
- **THEN** it SHALL call parse_markdown and return its result

#### Scenario: Unsupported type
- **WHEN** parse_document is called with file_type="csv"
- **THEN** it SHALL raise ValueError
