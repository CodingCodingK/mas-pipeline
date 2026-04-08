## 1. Pipeline YAML

- [x] 1.1 创建 `pipelines/courseware_exam.yaml`：4 节点线性管线（parser → analyzer → exam_generator → exam_reviewer），配置正确的 input/output 字段

## 2. Agent 角色文件

- [x] 2.1 创建 `agents/parser.md`：model_tier=strong, tools=[read_file]，课件解析 prompt
- [x] 2.2 创建 `agents/analyzer.md`：model_tier=medium, tools=[]，知识点分析 prompt
- [x] 2.3 创建 `agents/exam_generator.md`：model_tier=medium, tools=[search_docs, read_file]，RAG 出题 prompt
- [x] 2.4 创建 `agents/exam_reviewer.md`：model_tier=medium, tools=[]，审题 prompt

## 3. 验证脚本

- [x] 3.1 创建 `scripts/test_courseware_pipeline.py`：YAML 加载、节点结构、依赖推导、角色文件解析、工具池校验
