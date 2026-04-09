# mas-pipeline — Progress Log

## Current Status (2026-04-09)

**Phase 0: ✅ Done | Phase 1: ✅ Done (4/4 specs) | Phase 2: ✅ Done (9/9 specs) | Phase 3: ✅ Done (3/3 specs) | Phase 4: ✅ Done (3/3 specs) | Phase 5-7: Not started**

Next: Phase 5 — Extension Layer（hooks / skills / langgraph / permission / mcp / event-bus / streaming / sandbox）

---

## Completed Work

### Phase 0 — Infrastructure ✅

All done, including OpenSpec initialization.

Git commit: `e7c4773 feat(phase0): implement config system, database layer, and FastAPI entry`

Implemented:
- `pyproject.toml` — project metadata + dependencies (Python 3.12)
- `docker-compose.yaml` — PG16+pgvector:5433, Redis7:6379
- `scripts/init_db.sql` — 11 tables + indices + seed data
- `config/settings.yaml` — global config
- `src/project/config.py` — YAML loading + env var substitution + 4-layer merge
- `src/db.py` — async PG + Redis connection layer
- `src/main.py` — FastAPI + lifespan + health endpoint
- `scripts/verify_phase0.py` — Phase 0 verification script
- `ruff.toml` — lint config

### Phase 1.1 — llm-adapter ✅

Git commit: `8d02172 feat(llm): add unified LLM adapter with OpenAI-compatible provider support`
OpenSpec: archived at `openspec/changes/archive/2026-04-07-llm-adapter/`
Specs synced: `openspec/specs/llm-call/`, `openspec/specs/llm-routing/`

Implemented:
- `src/llm/adapter.py` — Usage / ToolCallRequest / LLMResponse dataclass + LLMAdapter ABC
- `src/llm/openai_compat.py` — OpenAICompatAdapter (request building, response parsing, thinking extraction, stream fallback, exponential backoff retry)
- `src/llm/router.py` — prefix mapping + tier resolution + route() function
- `scripts/test_llm_adapter.py` — verification script

Key design decisions (confirmed with user one by one during explore):
1. `Usage` as dataclass aligned with telemetry_events table (input_tokens / output_tokens / thinking_tokens)
2. `thinking: str | None` added in Phase 1 for forward compatibility
3. `call()` uses `**kwargs` passthrough, no CallOptions wrapper
4. `call_stream` deferred to Phase 5, Phase 1 ABC only has `call`
5. Router uses hardcoded prefix dict, raises error on no match
6. Self-written retry (1s→2s→4s), only retries 429/5xx, max 3 attempts

Implementation notes:
- User's OpenAI proxy (api-vip.codex-for.me) requires `stream=true`
- Added auto stream fallback in `_request()`: detects 400 + "stream" keyword → switches to `_request_stream()` to consume SSE and reassemble full response
- `delta.get("tool_calls")` may return None instead of missing key, guarded with `(x or [])`

Test verified:
```
route("light") → gpt-5.4 → openai provider → call → stream fallback → LLMResponse(content="Hello!", usage=Usage(12, 6, 0))
```

### Phase 1.2 — tool-system ✅

OpenSpec: archived at `openspec/changes/archive/2026-04-07-tool-system/`
Specs synced: `openspec/specs/tool-execution/`, `openspec/specs/tool-builtins/`

Implemented:
- `src/tools/base.py` — Tool ABC, ToolResult dataclass, ToolContext dataclass
- `src/tools/params.py` — cast_params (type coercion) + validate_params (JSON Schema validation)
- `src/tools/registry.py` — ToolRegistry: register, get, list_definitions (with name filtering)
- `src/tools/orchestrator.py` — partition_tool_calls + ToolOrchestrator.dispatch (safe concurrent, unsafe serial)
- `src/tools/builtins/read_file.py` — ReadFileTool (offset/limit, line numbers, 30K truncation)
- `src/tools/builtins/shell.py` — ShellTool (120s timeout, 30K truncation, dynamic safety, cwd persistence)
- `scripts/test_tool_system.py` — End-to-end verification

Key design decisions (confirmed during explore):
1. `is_concurrency_safe(params)` + `is_read_only(params)` — two methods, both accept params for dynamic judgment
2. Shell safety: whitelist prefixes + compound command split + variable/redirect detection (~30 lines vs CC's 2000)
3. ToolResult(output, success, metadata) — no CC's newMessages/contextModifier/mcpMeta (not needed until Phase 4-5)
4. cast → validate → call pipeline: auto-fix LLM type mistakes before validation
5. Manual tool registration (CC also does this with 40+ tools)
6. Shell cwd persistence: sentinel-based pwd capture after each command

### Phase 1.4 — context-builder ✅

OpenSpec: archived at `openspec/changes/archive/2026-04-07-context-builder/`
Specs synced: `openspec/specs/context-builder/`

Implemented:
- `src/agent/context.py` — parse_role_file + build_system_prompt + build_messages
- `agents/general.md` — 第一个 agent 角色文件（通用助手）
- `scripts/test_context_builder.py` — 8 项单元测试
- `scripts/test_single_agent.py` — Phase 1 端到端验收（真实 LLM 调用）
- `ruff.toml` — 增加 scripts/ 目录 E402 忽略

Key design decisions:
1. parse_role_file 用 PyYAML 分离 frontmatter，无新依赖
2. 系统提示 4 层拼接：identity → role → memory(Phase 3) → skill(Phase 5)
3. messages 组装在 loop 外部，OpenAI 格式 system + history + user
4. runtime_context 追加到 system prompt 末尾
5. Anthropic 格式转换在 adapter 层做（Phase 4）

Phase 1 端到端验收通过：
```
parse role → build prompt → build messages → AgentState → agent_loop → LLM → read_file tool call → result → final reply
[PASS] All 4 verification checks passed (light tier / gpt-5.4)
```

### Phase 2.1 — user-system ✅

Git commit: `b79198c feat(auth): add single-user identity system for Phase 2 foundation`
OpenSpec: archived at `openspec/changes/archive/2026-04-07-user-system/`
Specs synced: `openspec/specs/user-identity/`

已实现：
- `src/auth/user.py` — get_current_user() 从 settings.yaml 读 default_user，ORM 查询 + 缓存
- `src/project/config.py` — 新增 DefaultUserConfig（name, email）
- `src/models.py` — 引入 SQLAlchemy ORM，User model 替换原 Pydantic dataclass
- `scripts/test_user_system.py` — 验证脚本

关键设计决策：
1. 单用户模式，从 settings.yaml 读 default_user 配置
2. 引入 SQLAlchemy ORM 替换所有 raw SQL（用户确认："用，目前的sql都用orm吧，后续也用"）
3. 所有 ORM model 集中在 `src/models.py`（DeclarativeBase）
4. get_current_user() 模块级缓存，避免重复查询

### Phase 2.2 — project-manager ✅

Git commit: `4f0ed7e feat(project): add ORM model layer and project manager CRUD`
OpenSpec: archived at `openspec/changes/archive/2026-04-07-project-manager/`
Specs synced: `openspec/specs/project-crud/`

已实现：
- `src/project/manager.py` — create/get/list/update/archive 五个 CRUD 函数
- `src/models.py` — 新增 Project ORM model
- `scripts/test_project_manager.py` — 5 项测试

关键设计决策：
1. archive_project 软删除（status='archived'），list_projects 只返回 active
2. update_project 支持批量更新 + 自动 updated_at = func.now()
3. get/update/archive 都带 user_id 参数，确保数据隔离

### Phase 2.3 — file-manager ✅

Git commit: `24bd97f feat(files): add file manager with upload, list, delete, and path lookup`
OpenSpec: archived at `openspec/changes/archive/2026-04-08-file-manager/`
Specs synced: `openspec/specs/file-management/`

已实现：
- `src/files/manager.py` — upload/list_files/delete_file/get_file_path
- `src/models.py` — 新增 Document ORM model
- `scripts/test_file_manager.py` — 6 项测试

关键设计决策：
1. 扩展名白名单校验（pdf/pptx/md/docx/png/jpg/jpeg）
2. shutil.copy2 复制到 uploads/{project_id}/，原文件不动
3. 删除时同时清理 DB 记录和物理文件

### Phase 2.4 — AgentRun 记录（原 task-system）✅

Git commit: `7bf88aa feat(task): add task system with DAG dependencies and row-level locking`
OpenSpec: archived at `openspec/changes/archive/2026-04-08-task-system/`
Specs synced: `openspec/specs/agent-run-lifecycle/`（原 task-lifecycle，已重命名+重写）

已实现（经 Task→AgentRun 重构后）：
- `src/agent/runs.py` — create_agent_run/complete_agent_run/fail_agent_run/list_agent_runs/get_agent_run
- `src/models.py` — AgentRun ORM model（表名 agent_runs，默认 status=running）
- `scripts/init_db.sql` — agent_runs 表（替代 tasks 表）

**Task→AgentRun 重构**（深度调研 CC 源码后）：
> CC 有两套独立 "task" 系统：AgentTool（内存 AppState，spawn 跟踪）和 TaskCreate（文件 JSON，swarm mode）。
> CC Coordinator spawn 子 agent 走 AgentTool，不经过 TaskCreate，无 blockedBy 约束。
> 我们的 Task 对标 AgentTool 系统——改名 AgentRun，定位为纯审计记录。
> 系统控制流通过 asyncio.Queue 通知队列驱动（对标 CC commandQueue），不查 DB。
>
> 已删除：claim_task / check_blocked / blocked_by / AlreadyClaimedError / src/task/ 目录
> 已删除：task_create / task_update / task_list / task_get 四个 LLM 工具
> 已删除 spec：openspec/specs/task-tools/

### Phase 2.5 — SubAgent 机制 ✅

OpenSpec: archived at `openspec/changes/archive/2026-04-08-subagent/`
Specs synced: `openspec/specs/agent-factory/`, `openspec/specs/spawn-agent/`, `openspec/specs/task-tools/`, `openspec/specs/pipeline-run/`

已实现：
- `src/models.py` — 新增 PipelineRun ORM model
- `src/engine/run.py` — 最小 create_run（UUID run_id + status=running）
- `src/tools/builtins/__init__.py` — get_all_tools() 全局工具池 + AGENT_DISALLOWED_TOOLS
- `src/agent/factory.py` — create_agent 工厂（role 解析 → adapter 路由 → 工具过滤 → AgentState）
- `src/tools/builtins/spawn_agent.py` — SpawnAgentTool（异步后台）+ extract_final_output + format_task_notification
- `scripts/test_subagent.py` — 27 项检查全通过

关键设计决策（经 Task→AgentRun 重构后更新）：
1. AgentRun 纯审计记录：spawn_agent 创建 AgentRun 记录，但控制流不依赖 DB
2. 通知队列驱动：spawn_agent 完成时推 notification 到 parent_state.notification_queue（asyncio.Queue）
3. 异步后台执行：spawn 立即返回 agent_run_id，子 Agent asyncio.create_task 后台跑
4. 全局工具池：get_all_tools() 只含 read_file/shell/spawn_agent，子 Agent 禁用 spawn_agent
5. task_description 作为 user message（与 CC 一致）
6. 输出提取：倒序找最后一条有 text 的 assistant 消息（与 CC finalizeAgentTool 一致）
7. abort_signal 共享：父子同一个 Event 实例
8. ToolContext 新增 parent_state 字段：spawn_agent 通过它访问父 AgentState 的 notification_queue
9. AgentState 新增 notification_queue + running_agent_count 字段

---

### Phase 2.6 — Workflow Run 管理 ✅

OpenSpec: archived at `openspec/changes/archive/2026-04-08-workflow-run/`
Specs synced: `openspec/specs/pipeline-run/spec.md`（覆盖更新）

已实现：
- `src/engine/run.py` — 完整 CRUD: create_run / get_run / list_runs / update_run_status / finish_run
- RunStatus(str, Enum): PENDING / RUNNING / COMPLETED / FAILED
- 状态机校验: VALID_TRANSITIONS + InvalidTransitionError
- Redis Hash 同步: 每次状态变更写 `workflow_run:{run_id}`
- `scripts/test_workflow_run.py` — 35 项检查全通过

附带变更：
- Rename: PipelineRun → WorkflowRun, pipeline_runs → workflow_runs（全局）
- `scripts/init_db.sql` 表名更新
- `src/models.py` ORM class 更新
- 数据库重建（docker compose down -v && up）

### Phase 2.7 — Pipeline Engine ✅

OpenSpec: archived at `openspec/changes/archive/2026-04-08-pipeline-engine/`
Specs synced: `openspec/specs/pipeline-definition/`, `openspec/specs/pipeline-execution/`, `openspec/specs/pipeline-run/`（修改）

已实现：
- `src/engine/pipeline.py` — load_pipeline + execute_pipeline + reactive 调度
  - NodeDefinition / PipelineDefinition / PipelineResult dataclass
  - YAML 加载 + 依赖推导（input/output 自动推导，无 edges）
  - 校验：output 唯一性、input 引用合法性、无环检测（Kahn 算法）
  - reactive 调度循环：pending/running/completed + asyncio.wait(FIRST_COMPLETED)
  - 节点执行：create_agent + agent_loop + extract_final_output + Task 记录
  - 失败节点下游级联 skipped，不影响无关分支
  - abort_signal 共享，入口节点用 user_input，非入口节点拼接上游 output
- `pipelines/test_linear.yaml` — 3 节点线性测试管线
- `pipelines/test_parallel.yaml` — 6 节点并行分支测试管线
- `scripts/test_pipeline_engine.py` — 31 项检查全通过
- `scripts/test_pipeline_scheduling.py` — 16 项检查全通过（并行启动/线性顺序/数据流）

关键设计决策：
1. YAML 只有 nodes（name/role/input/output），无 edges，依赖从 input/output 自动推导
2. 工具和模型跟 role 文件走，YAML 不重复声明
3. 所有节点统一当 Agent 跑，不区分 agent/transform
4. reactive 并行：就绪即启动，不分层，asyncio.wait(FIRST_COMPLETED)
5. 上游输出注入下游 task_description，入口节点用 user_input
6. Engine 只接收 run_id，不创建 WorkflowRun
7. PipelineResult 包含所有中间节点输出

### Phase 3 — Session, Memory & Compact ✅

Git commit: `1f8ee7a feat(phase3): add session manager, memory system, and compact`
OpenSpec: archived at `openspec/changes/archive/2026-04-09-session-memory-compact/`
Specs synced: 4 新增 + 3 修改
- 新增: `session-manager/`, `memory-store/`, `memory-tools/`, `compact/`
- 修改: `agent-loop/` (TOKEN_LIMIT + compact 集成), `context-builder/` (memory_context), `tool-builtins/` (6 tools)

已实现：
- `src/session/manager.py` — Conversation CRUD (PG) + Agent Session 热存储 (Redis List, TTL 24h) + archive + orphan cleanup
- `src/memory/store.py` — Memory CRUD (write/update/delete/list/get) + type 校验 (fact/preference/context/instruction)
- `src/memory/selector.py` — select_relevant: LLM 相关性判断，返回 top-K 完整内容
- `src/tools/builtins/memory.py` — MemoryReadTool (list/get) + MemoryWriteTool (write/update/delete)
- `src/agent/compact.py` — 三级压缩: micro (清旧 tool_result) → auto (85% 阈值, LLM 摘要) → reactive (context_length_exceeded, 只试一次)
- `src/agent/loop.py` — compact 集成（每轮 micro+auto+blocking，LLM 异常时 reactive）
- `src/agent/context.py` — build_system_prompt 新增 memory_context 参数
- `src/models.py` — 4 个新 ORM: Conversation, AgentSessionRecord, Memory, CompactSummary
- `src/project/config.py` — CompactConfig (百分比阈值) + context_windows 配置
- `scripts/init_db.sql` — user_sessions → conversations 表重命名

关键设计决策：
1. UserSession → Conversation 重命名（消除与 Agent Session 的歧义）
2. Compact 百分比阈值 (85%/95%)，而非绝对值，适配不同模型 context_window
3. Context window 三级查找: settings.yaml > 内置默认表 (11 模型) > 128K 兜底
4. Token 估算: 字符数/4 近似法，误差 ~20%，阈值判断足够
5. Memory 两条路径: 被动注入 (select_relevant → system prompt) + 主动工具 (memory_read/write)
6. Agent Session: Redis List 热存储 + PG 冷归档，TTL 24h
7. Orphan tool_result 清理: 加载时扫描，删除无匹配 assistant tool_call 的 tool 消息

测试: 143 项检查 (4 个脚本) + blog pipeline 回归测试 31 项，全部通过
- `scripts/test_session_manager.py` — 28 checks
- `scripts/test_memory_system.py` — 37 checks
- `scripts/test_compact.py` — 35 checks
- `scripts/test_loop_compact.py` — 12 checks

附带文档: `.plan/compact_and_memory.md` — Compact 三级机制 + Memory 流程 + CC Memory 对比

TODO: Memory 漂移保护（CC 有 TRUSTING_RECALL_SECTION，我们需要在 memory_context 注入时加漂移提醒）

### Phase 4.1 — Anthropic Adapter ✅

Git commit: `3615d45 feat(phase4): add Anthropic adapter and RAG pipeline`
OpenSpec: archived at `openspec/changes/archive/2026-04-09-anthropic-adapter/`
Specs synced: 1 新增 + 1 修改
- 新增: `anthropic-messages/`
- 修改: `llm-routing/`（claude- → AnthropicAdapter）

已实现：
- `src/llm/anthropic.py` — AnthropicAdapter: Messages API 请求构造、响应解析、tool_use/thinking/multimodal content blocks 转换、重试
- `src/llm/router.py` — `claude-` 前缀路由到 AnthropicAdapter

关键设计决策：
1. 内部消息格式不变（OpenAI style），adapter 内部做 Anthropic 格式转换
2. 多模态：每个 Adapter 原生支持 content blocks，不走专用解析 Agent（信息零损失）
3. system 消息从 messages 提取为 Anthropic 独立 `system` 参数
4. 相邻同角色消息合并（Anthropic 要求严格交替）
5. tool result 转为 user message 下的 tool_result content block

测试: 63 项 adapter 测试 + 31 项回归测试

### Phase 4.2 — RAG Pipeline ✅

Git commit: 同上 `3615d45`
OpenSpec: archived at `openspec/changes/archive/2026-04-09-rag-pipeline/`
Specs synced: 5 新增 + 1 修改
- 新增: `document-parsing/`, `document-chunking/`, `embedding/`, `vector-retrieval/`, `search-docs-tool/`
- 修改: `tool-builtins/`（7 tools）

已实现：
- `src/rag/parser.py` — 文档解析: MD(直读), PDF(pymupdf4llm→Markdown+页面图片渲染), DOCX(python-docx)
- `src/rag/chunker.py` — 分块: 标题/段落/硬切 + overlap + 元数据
- `src/rag/embedder.py` — Embedding: OpenAI text-embedding-3-small, 批量≤100
- `src/rag/retriever.py` — 检索: pgvector 余弦相似度, project_id 隔离
- `src/rag/ingest.py` — 编排: 解析→分块→Embedding→存储→更新 Document
- `src/tools/builtins/search_docs.py` — SearchDocsTool (query+top_k, project_id 过滤)
- `src/models.py` — DocumentChunk ORM (pgvector Vector(1536))

关键设计决策：
1. Embedding 全局统一 text-embedding-3-small，换模型需全量 re-embed
2. PDF 混合策略: pymupdf4llm 转 Markdown(主路径) + 含图页面渲染存图(Agent 多模态直看)
3. 不引入 LangChain（~170 行自己写 vs 100+ 传递依赖）
4. pgvector 暴力扫描，IVFFlat 索引 <10K chunks 时不需要
5. Re-ingest 支持: 先删旧 chunks 再插新

测试: 49 项 RAG 测试 + 31 项回归测试

### Phase 4.3 — Courseware Pipeline ✅

OpenSpec: archived at `openspec/changes/archive/2026-04-09-courseware-pipeline/`
Specs synced: 1 新增
- 新增: `courseware-pipeline/`

已实现：
- `pipelines/courseware_exam.yaml` — 4 节点线性管线（parser → analyzer → exam_generator → exam_reviewer）
- `agents/parser.md` — 课件解析（strong tier, read_file, 多模态图表理解）
- `agents/analyzer.md` — 知识点分析（medium tier, 无工具）
- `agents/exam_generator.md` — RAG 出题（medium tier, search_docs + read_file）
- `agents/exam_reviewer.md` — 审题（medium tier, 无工具）
- `scripts/test_courseware_pipeline.py` — 39 项检查

关键设计决策：
1. parser 用 strong tier（课件含图表/公式，多模态理解需要更强模型），其余三个 medium
2. exam_generator 通过 search_docs 检索课件原文，确保题目基于真实教材
3. 纯配置变更，无代码修改（复用现有 pipeline engine + RAG + multimodal adapter）

测试: 39 项 courseware 测试 + 31 项回归测试

---

## Spec Roadmap

### Phase 1 — Minimum Viable Agent
| # | Spec | Status | Depends On |
|---|------|--------|------------|
| 1 | `llm-adapter` | ✅ Done | — |
| 2 | `tool-system` | ✅ Done | — |
| 3 | `agent-loop` | ✅ Done | 1+2 |
| 4 | `context-builder` | ✅ Done | 3 |

### Phase 2 — Project Layer + Multi-Agent Pipeline
| 5 | `user-system` | ✅ Done | — |
| 6 | `project-manager` | ✅ Done | 5 |
| 7 | `file-manager` | ✅ Done | 6 |
| 8 | `agent-run-lifecycle` (原 task-system) | ✅ Done | — |
| 9 | `subagent` | ✅ Done | 3+8 |
| 9.5 | `workflow-run` | ✅ Done | 9 |
| 10 | `pipeline-engine` | ✅ Done | 9.5 |
| 11 | `coordinator` | ✅ Done | 10 |
| 12 | `blog-pipeline` | ✅ Done | 11+7 |

### Phase 3 — Memory & Compaction
| 12 | `session-manager` | ✅ Done | 3 |
| 13 | `memory-system` | ✅ Done | 4 |
| 14 | `compact` | ✅ Done | 3 |

### Phase 4 — Multimodal & RAG
| 15 | `anthropic-adapter` | ✅ Done | 1 |
| 16 | `rag-pipeline` | ✅ Done | 7 |
| 17 | `courseware-pipeline` | ✅ Done | 16+10 |

### Phase 5 — Extension Layer
| # | Spec | Status |
|---|------|--------|
| 5.7 | streaming | ✅ Done |
| 5.1 | hooks | ✅ Done |
| 5.2 | permission | ✅ Done |
| 5.3 | skill | ✅ Done |
| 5.4 | mcp | ✅ Done |
| 5.5 | claw (channel-layer) | ✅ Done |
| 5.6 | langgraph | 🔲 |
| 5.8 | sandbox | 🔲 |

### Phase 6-7 — API + Frontend + Tests (to be split)

---

## OpenSpec Artifacts

- Main specs: `openspec/specs/<capability>/spec.md`
- Active changes: `openspec/changes/<name>/`
- Archive: `openspec/changes/archive/YYYY-MM-DD-<name>/`

Current main specs:
- `openspec/specs/llm-call/spec.md`
- `openspec/specs/llm-routing/spec.md`
- `openspec/specs/tool-execution/spec.md`
- `openspec/specs/tool-builtins/spec.md`
- `openspec/specs/agent-loop/spec.md`
- `openspec/specs/context-builder/spec.md`
- `openspec/specs/user-identity/spec.md`
- `openspec/specs/project-crud/spec.md`
- `openspec/specs/file-management/spec.md`
- `openspec/specs/agent-run-lifecycle/spec.md` (原 task-lifecycle，重构后)
- `openspec/specs/agent-factory/spec.md`
- `openspec/specs/spawn-agent/spec.md`
- `openspec/specs/pipeline-run/spec.md`
- `openspec/specs/pipeline-definition/spec.md`
- `openspec/specs/pipeline-execution/spec.md`
> 已删除: `task-tools/spec.md`（CC Coordinator 不需要 task_* 工具）

Active changes:
- (none — courseware-pipeline archived to `openspec/changes/archive/2026-04-09-courseware-pipeline/`)

Main specs 新增（Phase 2.8）：
- `openspec/specs/coordinator-loop/spec.md`
- `openspec/specs/coordinator-role/spec.md`
- `openspec/specs/coordinator-routing/spec.md`

Main specs 新增（Phase 3）：
- `openspec/specs/session-manager/spec.md`
- `openspec/specs/memory-store/spec.md`
- `openspec/specs/memory-tools/spec.md`
- `openspec/specs/compact/spec.md`

Main specs 新增（Phase 4）：
- `openspec/specs/anthropic-messages/spec.md`
- `openspec/specs/document-parsing/spec.md`
- `openspec/specs/document-chunking/spec.md`
- `openspec/specs/embedding/spec.md`
- `openspec/specs/vector-retrieval/spec.md`
- `openspec/specs/search-docs-tool/spec.md`
- `openspec/specs/courseware-pipeline/spec.md`

Main specs 新增/修改（Phase 5 Streaming）：
- `openspec/specs/stream-events/spec.md`（新增）
- `openspec/specs/stream-agent-loop/spec.md`（新增）

Main specs 新增/修改（Phase 5 Hooks）：
- `openspec/specs/hook-events/spec.md`（新增）
- `openspec/specs/hook-runner/spec.md`（新增）
- `openspec/specs/hook-config/spec.md`（新增）
- `openspec/specs/tool-execution/spec.md`（修改：hooks 集成）
- `openspec/specs/spawn-agent/spec.md`（修改：SubagentStart/End）
- `openspec/specs/pipeline-execution/spec.md`（修改：PipelineStart/End）

Main specs 新增/修改（Phase 5 Permission）：
- `openspec/specs/permission-rules/spec.md`（新增）
- `openspec/specs/permission-integration/spec.md`（新增）
- `openspec/specs/agent-factory/spec.md`（修改：permission_mode + parent_deny_rules）
- `openspec/specs/pipeline-execution/spec.md`（修改：permission_mode 参数）

---

## Next Steps

1. ~~Phase 2.5 — SubAgent 机制~~ ✅
2. ~~Phase 2.6 — Workflow Run 管理~~ ✅
3. ~~Phase 2.7 — Pipeline Engine~~ ✅
4. ~~Phase 2.8 — Coordinator~~ ✅ (commit 50cfba4)
   - run_coordinator 路由函数 + coordinator_loop 通知队列驱动 + CoordinatorResult + 42 项测试
5. ~~Phase 2.9 — Blog Pipeline~~ ✅ (commit 9a3ae23)
   - WebSearchTool (Tavily API) + 3 角色文件 + blog_generation.yaml + 53 项测试
6. ~~Phase 3 — Session + Memory + Compact~~ ✅ (commit 1f8ee7a)
   - Conversation CRUD + Agent Session Redis/PG + Memory CRUD + LLM relevance selection + 三级 Compact + 143 项测试
7. ~~Phase 4.1 — Anthropic Adapter~~ ✅ (commit 3615d45)
   - AnthropicAdapter: Messages API + tool_use + thinking + multimodal + router 改造 + 63 项测试
8. ~~Phase 4.2 — RAG Pipeline~~ ✅ (同上 commit 3615d45)
   - 文档解析(MD/PDF/DOCX) + 分块 + Embedding + pgvector 检索 + search_docs 工具 + 49 项测试
9. ~~Phase 4.3 — Courseware Pipeline~~ ✅
   - 4 节点线性管线(parser→analyzer→exam_generator→exam_reviewer) + 4 角色文件 + 39 项测试
10. Phase 5 — Extension Layer **← 当前阶段**
    - 实施顺序：Streaming → Hooks → Permission → Skill → MCP → Event Bus → LangGraph → Sandbox
    - ~~5.7 Streaming~~ ✅ (commit 7136aab)
      - StreamEvent 9 类型统一事件模型 + OpenAI/Anthropic call_stream 双适配
      - agent_loop → AsyncGenerator[StreamEvent] + run_agent_to_completion() helper
      - coordinator_loop/spawn_agent/pipeline 全链路适配 + 145 项测试
    - ~~5.1 Hooks~~ ✅ (pending commit)
      - 9 事件类型 + command/prompt 执行器 + HookRunner 并行执行
      - Orchestrator 集成 PreToolUse deny/modify、PostToolUse additional_context
      - 生命周期集成 SubagentStart/End、PipelineStart/End
      - Factory 自动加载 settings.yaml + frontmatter hooks、注入 Orchestrator
      - 160 项测试全通过
    - ~~5.2 Permission~~ ✅ (pending commit)
      - PermissionMode (bypass/normal/strict) + PermissionRule `ToolName(fnmatch)` 语法
      - check_permission 纯函数 + PermissionChecker 类 + TOOL_CONTENT_FIELD 映射表
      - 注册为 PreToolUse callable hook、ask fallback deny（Phase 6 接 UI）
      - SubAgent 继承父级 deny 规则、permission_mode 最外层默认 NORMAL
      - HookConfig/HookRunner 扩展 callable 执行器类型
      - 115 项测试 + 77 项回归测试全通过
    - ~~5.3 Skill~~ ✅ (pending commit)
      - SkillDefinition + SkillResult 数据类型、skills/*.md 文件加载解析
      - substitute_variables ($ARGUMENTS/${PROJECT_ID}/${AGENT_ID}/${SKILL_DIR})
      - execute_inline (变量替换返回 SkillResult) + execute_fork (spawn 隔离子 agent)
      - SkillTool: 每 agent 实例、input {skill_name, args}、inline/fork 分发
      - _skill_layer: always=true 全文注入 + always=false XML 摘要
      - Factory 集成: role frontmatter skills 白名单、按需注册 SkillTool
      - 预置 skills: research (fork/web_search) + summarize (inline)
      - 125 项测试 (6 个脚本) 全通过
    - ~~5.4 MCP~~ ✅ (pending commit)
      - JSON-RPC 2.0 消息构建 + MCPTransport ABC (StdioTransport + HTTPTransport)
      - MCPClient: initialize 握手 + list_tools + call_tool + shutdown 全协议生命周期
      - MCPTool(Tool): `mcp__server__tool` 三段式命名，call() 转发到 MCPClient
      - MCPManager: Pipeline 级连接池，asyncio.gather 并发启动，故障隔离
      - Settings 新增 mcp_servers + mcp_default_access (all/none)
      - Factory 集成: role frontmatter mcp_servers 白名单 + default_access 逻辑
      - Pipeline 集成: execute_pipeline 内 MCPManager 生命周期管理 (start→nodes→shutdown)
      - 91 项测试 (7 个脚本) 全通过
    - ~~5.5 Claw (Channel Layer)~~ ✅
      - 原 Event Bus，重定义为外部通讯平台集成（见 `.plan/claw_design_notes.md`）
      - MessageBus: 两个 asyncio.Queue (inbound + outbound)，非 pub-sub
      - BaseChannel ABC + ChannelManager: 统一适配器接口，延迟注册，容错启停
      - Discord: WebSocket Gateway (HELLO→IDENTIFY→DISPATCH) + REST 发送 + 2000 字符分割 + 429 限流重试
      - QQ: qq-botpy SDK，C2C 私聊 + 群聊 @，OrderedDict LRU 消息去重
      - WeChat: ilinkai HTTP 长轮询，context_token 缓存，token 持久化，4000 字符分割
      - Gateway: per-message agent_loop dispatch，per-session asyncio.Lock 串行，cross-session 并发
      - ChatSession 模型 + Redis 热缓存 + PG 持久化，复用 Conversation 表
      - CLI 入口 + SIGINT/SIGTERM 优雅停机
      - 242 项测试 (9 个脚本) 全通过

### Phase 1.3 agent-loop — Design Decisions (explore completed)

Key decisions confirmed:
- **AgentState**: Method A — all deps inside (adapter, tools, orchestrator, tool_context). Mutable dataclass, runtime field mutation for Phase 5 Skill inline mode. No contextModifier pattern needed.
- **ToolContext**: Lightweight (agent_id, run_id, project_id, abort_signal), lives inside AgentState. Hooks/Permissions go in Orchestrator (Phase 5), not ToolContext.
- **Exit conditions**: Phase 1 `ExitReason(str, Enum)` — COMPLETED, MAX_TURNS, ABORT, ERROR. Returns ExitReason directly, no LoopResult wrapper.
- **Message format**: OpenAI dict `list[dict]`, arguments stored as dict in memory, thinking as non-standard field. Helper functions for construction.
- **Compact hooks**: 3 comment placeholders in loop (microcompact, autocompact+blocking_limit, reactive). `has_attempted_reactive_compact` field on AgentState.
- **Telemetry**: No Phase 1 reservation needed — pure sidecar, insert at Phase 6.
