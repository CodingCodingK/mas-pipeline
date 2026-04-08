## Context

已有基础设施：
- `documents` 表 + `Document` ORM：文件上传记录，有 `parsed`/`chunk_count` 字段
- `document_chunks` 表：pgvector 1536 维向量列，已有 CASCADE 删除到 documents
- `settings.yaml` 配了 `embedding.model: text-embedding-3-small`、`embedding.provider: openai`、`embedding.dimensions: 1536`
- File Manager：upload/list/delete/get_file_path
- OpenAI provider 已配置（embedding 走 OpenAI API）

## Goals / Non-Goals

**Goals:**
- 实现完整的 RAG 链路：文档解析 → 分块 → Embedding → pgvector 存储 → 向量检索
- 支持 MD/PDF/DOCX 三种格式
- PDF 混合策略：pymupdf4llm 提取 Markdown + 含图页面渲染存图
- Agent 可通过 search_docs 工具检索项目文档
- project_id 隔离，不同项目的文档互不可见

**Non-Goals:**
- 语义搜索 memory（Phase 4+ 如果需要再加）
- 上传自动触发 ingest（可选，不强制。Phase 6 API 层决定）
- IVFFlat 索引（init_db.sql 注释了，需要行数据后才能创建，暂不做）
- 图片的 LLM 描述 embedding（仅存储原图，Agent 检索时多模态直看）

## Decisions

### 1. 文档解析策略

| 格式 | 库 | 策略 |
|------|-----|------|
| MD | 内置 | 直接读文本 |
| PDF | pymupdf4llm | 转 Markdown（保留表格），含图页面额外渲染存图 |
| DOCX | python-docx | 提取段落文本，图片导出 |

PDF 的 pymupdf4llm 直接输出 Markdown 格式，表格自动转 Markdown table，效果比纯 pymupdf 好。

### 2. 分块策略

按段落分割，目标块大小 500-1000 字符，相邻块 overlap 100 字符。每块带元数据：
```python
@dataclass
class Chunk:
    content: str
    metadata: dict  # {doc_id, page, section, chunk_index}
```

分割优先级：`\n## `（二级标题）> `\n\n`（段落）> 字符数硬切。

### 3. Embedding 调用

直接用 httpx 调 OpenAI Embedding API（和 LLM adapter 类似模式），不经过 LLMAdapter。理由：Embedding API 格式完全不同于 Chat Completion，复用 adapter 抽象没有意义。

批量处理：每批最多 100 条文本，防止单次请求过大。

### 4. 向量检索

pgvector 余弦相似度（`<=>` 运算符），强制 `WHERE project_id = :pid` 隔离。返回 top-K 结果（默认 5），每个结果包含文本内容 + 元数据。

### 5. Ingest 编排

`ingest_document(project_id, doc_id)` 是一条龙编排函数：
1. 查 Document 记录，获取 file_path/file_type
2. 调 parser 解析文档 → 文本 + 图片
3. 调 chunker 分块 → list[Chunk]
4. 调 embedder 批量向量化 → list[vector]
5. 批量 INSERT document_chunks
6. 更新 Document.parsed=True, chunk_count=N

### 6. SearchDocsTool

和 WebSearchTool 结构一致，input_schema: `{"query": str, "top_k": int}`，自动从 ToolContext.project_id 获取项目 ID。concurrency_safe=True, read_only=True。

## Risks / Trade-offs

- **[PDF 质量]** pymupdf4llm 对复杂排版（多栏、嵌套表格）可能提取不完整 → 可接受，后续如有需要再加 LLM 辅助解析
- **[Embedding 成本]** 大文档可能产生很多 chunks → 单次 embed 调用受限于 API rate limit，批量处理缓解
- **[无 IVFFlat]** 暴力扫描在 chunks 少（<10K）时够快；超过后需创建 IVFFlat 索引 → Phase 6 再看
- **[图片存储]** PDF 渲染的页面图片存本地 uploads 目录 → 和 File Manager 保持一致的存储路径
