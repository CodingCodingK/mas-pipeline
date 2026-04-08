## 1. ORM + 依赖

- [x] 1.1 新增 `DocumentChunk` ORM 到 `src/models.py`（id, doc_id, chunk_index, content, embedding vector(1536), metadata JSONB）
- [x] 1.2 添加 `pymupdf4llm` 和 `python-docx` 到 `pyproject.toml` 依赖

## 2. 文档解析

- [x] 2.1 创建 `src/rag/parser.py`：ParseResult dataclass + parse_markdown + parse_pdf + parse_docx + parse_document 分发
- [x] 2.2 parse_pdf 实现：pymupdf4llm 转 Markdown，含图页面渲染 PNG 存到 images_dir

## 3. 分块

- [x] 3.1 创建 `src/rag/chunker.py`：Chunk dataclass + chunk_text（按标题/段落分割，overlap，元数据）

## 4. Embedding

- [x] 4.1 创建 `src/rag/embedder.py`：embed(texts) 调 OpenAI Embedding API，批量处理（每批 ≤100），读 settings.embedding 配置

## 5. 检索 + Ingest

- [x] 5.1 创建 `src/rag/retriever.py`：RetrievalResult dataclass + retrieve(project_id, query, top_k) pgvector 余弦相似度检索
- [x] 5.2 创建 `src/rag/ingest.py`：ingest_document(project_id, doc_id) 编排解析→分块→Embedding→存储→更新 Document 记录

## 6. LLM 工具

- [x] 6.1 创建 `src/tools/builtins/search_docs.py`：SearchDocsTool（query + top_k，ToolContext.project_id 过滤）
- [x] 6.2 修改 `src/tools/builtins/__init__.py`：get_all_tools() 加入 search_docs，总数 7

## 7. 测试

- [x] 7.1 编写 `scripts/test_rag.py`：chunker 测试（单块/多块/overlap/元数据）、embedder mock 测试、retriever mock 测试、search_docs 工具测试、get_all_tools 数量验证
- [x] 7.2 回归测试：运行 `scripts/test_blog_pipeline.py` 确认无破坏
