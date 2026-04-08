## Why

Phase 4 的核心业务场景：用户上传课件 PDF，系统自动解析、分析知识点、生成考题并审查。这是 RAG + 多模态能力的首个真实业务管线，验证 Phase 4.1 (Anthropic Adapter) 和 4.2 (RAG Pipeline) 的端到端集成。

## What Changes

- 新增 `pipelines/courseware_exam.yaml`：4 节点线性管线（解析 → 分析 → 出题 → 审题）
- 新增 4 个 Agent 角色文件：
  - `agents/parser.md` — 课件解析 Agent（strong tier，多模态，读取课件内容+图表）
  - `agents/analyzer.md` — 知识点分析 Agent（medium tier，从解析结果中提炼知识点）
  - `agents/exam_generator.md` — 出题 Agent（medium tier，RAG 约束：只检索当前 project 的文档）
  - `agents/exam_reviewer.md` — 审题 Agent（medium tier，检查题目质量和答案正确性）
- 新增 `scripts/test_courseware_pipeline.py`：管线结构、角色文件、依赖推导的验证脚本

## Capabilities

### New Capabilities
- `courseware-pipeline`: 课件分析+出题管线的 YAML 定义、4 个角色文件及其工具配置、管线结构验证

### Modified Capabilities
（无 spec 级别的行为变更——复用 pipeline-definition、pipeline-execution、search-docs-tool 等现有能力）

## Impact

- 新增文件：1 YAML + 4 角色 MD + 1 测试脚本
- 无代码变更：复用现有 pipeline engine、RAG retriever、多模态 adapter
- 依赖：pymupdf4llm（已在 4.2 引入）、search_docs 工具（已在 4.2 实现）
