## 1. WebSearchTool

- [x] 1.1 在 `config/settings.yaml` 新增 `tavily.api_key: ${TAVILY_API_KEY}` 配置
- [x] 1.2 实现 `src/tools/builtins/web_search.py` — WebSearchTool：input_schema（query + max_results）、call（httpx.post Tavily API）、结果格式化、错误处理、is_read_only=True、is_concurrency_safe=True
- [x] 1.3 在 `src/tools/builtins/__init__.py` 注册 WebSearchTool 到 get_all_tools()

## 2. 角色文件

- [x] 2.1 编写 `agents/researcher.md` — frontmatter（tools: [web_search, read_file], model_tier: medium）+ 调研 prompt（搜索指引、报告结构要求、引用来源）
- [x] 2.2 编写 `agents/writer.md` — frontmatter（tools: [read_file], model_tier: medium）+ 写作 prompt（博客结构、Markdown 格式、引用调研数据）
- [x] 2.3 编写 `agents/reviewer.md` — frontmatter（tools: [], model_tier: medium）+ 审校 prompt（检查逻辑/语法/结构、输出终稿）

## 3. 管线定义

- [x] 3.1 编写 `pipelines/blog_generation.yaml` — 3 节点线性管线（researcher → writer → reviewer）

## 4. 验证

- [x] 4.1 编写 `scripts/test_web_search.py` — WebSearchTool 单元测试（真实 API 调用 + 错误场景 mock）
- [x] 4.2 编写 `scripts/test_blog_pipeline.py` — 端到端验证（加载 YAML、角色解析、管线执行）
