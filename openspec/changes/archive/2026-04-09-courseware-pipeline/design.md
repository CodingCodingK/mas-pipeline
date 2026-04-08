## Context

Phase 4.1 (Anthropic Adapter) 和 4.2 (RAG Pipeline) 已完成，提供了多模态 LLM 调用和文档检索能力。Phase 4.3 是第一个真正把这些能力串起来的业务管线——课件分析+出题。

现有 blog_generation 管线（3 节点线性：researcher → writer → reviewer）已验证 pipeline engine 的正确性。courseware_exam 管线遵循相同模式，但引入 RAG 和多模态工具。

## Goals / Non-Goals

**Goals:**
- 定义 4 节点线性管线 YAML（parser → analyzer → exam_generator → exam_reviewer）
- 为每个节点编写角色文件，配置正确的 model_tier 和 tools
- parser 使用 strong tier（多模态理解需要更强模型）+ read_file（读取课件原文）
- exam_generator 使用 search_docs 从当前 project 检索课件内容（RAG）
- 验证管线结构、依赖推导、角色文件完整性

**Non-Goals:**
- 不修改 pipeline engine 代码（复用现有 execute_pipeline）
- 不修改 RAG 检索逻辑（search_docs 已天然 project_id 隔离）
- 不实现 ingest 自动触发（文件上传后手动或 API 层触发 ingest，属 Phase 6）
- 不做 reviewer 中断/人工审核（属 Phase 5 LangGraph 能力）

## Decisions

### 1. 管线拓扑：4 节点线性

```
parser → analyzer → exam_generator → exam_reviewer
  │          │            │               │
 解析课件   分析知识点    出题           审题
```

不用并行分支——出题必须基于知识点分析结果，审题必须基于题目。严格顺序。

替代方案：analyzer 和 exam_generator 并行 → 不可行，出题需要知识点作为输入。

### 2. parser 用 strong tier

课件 PDF 含大量图表、公式、复杂排版。strong tier（claude 系列）多模态理解能力显著强于 medium tier。这是唯一用 strong tier 的节点——其他三个节点处理纯文本，medium 足够。

工具配置：`[read_file]`。parser 的输入是上游传来的课件路径/内容描述，用 read_file 读取解析后的文本。

### 3. exam_generator 用 search_docs

出题 Agent 通过 `search_docs` 检索当前 project 的课件内容，确保题目基于真实教材而非 LLM 臆想。search_docs 已内置 project_id 隔离（Phase 4.2），无需额外约束。

工具配置：`[search_docs, read_file]`。

### 4. 数据流设计

```yaml
parser:          input=无(入口节点), output=parsed_content
analyzer:        input=[parsed_content],  output=knowledge_points
exam_generator:  input=[knowledge_points], output=exam_draft
exam_reviewer:   input=[exam_draft],       output=final_exam
```

每个节点的 output 名清晰描述其产出物，避免歧义。

### 5. 测试策略

与 blog_generation 一致：纯结构验证（YAML 加载、依赖推导、角色文件解析、工具池校验），不做真实 LLM 调用。

## Risks / Trade-offs

- **[parser 输入格式]** parser 是入口节点，user_input 需要包含足够信息（如文件路径或课件内容）。→ 缓解：角色 prompt 明确说明输入预期格式。
- **[RAG 前置依赖]** exam_generator 用 search_docs 时，文档必须已经 ingest 过。→ 缓解：角色 prompt 提示"若检索无结果，说明课件尚未索引"。
- **[strong tier 成本]** parser 用 strong tier 单次调用成本较高。→ 可接受：课件解析是一次性操作，不频繁。
