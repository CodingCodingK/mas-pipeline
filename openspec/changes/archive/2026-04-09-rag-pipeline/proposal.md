## Why

当前 File Manager 只做文件的上传/存储/删除，Agent 无法基于项目文档内容进行检索和引用。RAG（Retrieval-Augmented Generation）让 Agent 能根据用户上传的文档回答问题、生成内容。

DB 已有 `document_chunks` 表（pgvector 1536 维）和 `documents` 表的 `parsed`/`chunk_count` 字段，基础设施就绪，需要实现解析→分块→Embedding→检索的完整链路。

## What Changes

- 新增文档解析模块：支持 MD、PDF（pymupdf4llm 转 Markdown + 页面渲染存图）、DOCX（python-docx 提取）
- 新增文本分块器：按标题/段落分割，带 overlap，每块附带元数据
- 新增 Embedding 模块：调 OpenAI text-embedding-3-small API，批量处理
- 新增向量检索模块：pgvector 余弦相似度，project_id 隔离
- 新增 `search_docs` LLM 工具：Agent 可调用检索项目文档
- 新增 `DocumentChunk` ORM 模型
- 修改 `get_all_tools()`：新增 search_docs，总数从 6 → 7
- 新增 `ingest_document` 编排函数：解析 → 分块 → Embedding → 存储一条龙
- 修改 `Document` ORM：`parsed` 和 `chunk_count` 字段在 ingest 完成后更新

## Capabilities

### New Capabilities
- `document-parsing`: 文档解析（MD/PDF/DOCX → 文本 + 图片提取）
- `document-chunking`: 文本分块（标题/段落分割 + overlap + 元数据）
- `embedding`: 文本向量化（OpenAI Embedding API 调用 + 批量处理）
- `vector-retrieval`: 向量检索（pgvector 余弦相似度 + project_id 隔离）
- `search-docs-tool`: Agent 检索工具（封装 retriever，自动 project_id 过滤）

### Modified Capabilities
- `tool-builtins`: get_all_tools() 新增 search_docs，总数 7

## Impact

- 新增 `src/rag/` 目录：parser.py, chunker.py, embedder.py, retriever.py, ingest.py
- 新增 `src/tools/builtins/search_docs.py`
- 修改 `src/tools/builtins/__init__.py`（增加 search_docs）
- 修改 `src/models.py`（新增 DocumentChunk ORM）
- 新增依赖：`pymupdf4llm`（PDF 解析）、`python-docx`（DOCX 解析）
- 测试：新增 RAG 验证脚本
