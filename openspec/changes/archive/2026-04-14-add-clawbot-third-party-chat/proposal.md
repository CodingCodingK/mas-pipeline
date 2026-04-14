## Why

第三方 chat 渠道（Discord/QQ/WeChat）当前由 `Gateway` 写死绑一个 project、用 `assistant` 这一个单 agent 回复（`src/bus/gateway.py:42`）。这让群里的 bot 只能当"单项目助手"：不知道有哪些 project、不能主动跑 pipeline、pipeline 跑起来后群里收不到进度、interrupt 阻塞无人知。收尾阶段 7.1 要把第三方 chat 升级成一个真正的"群里随身 assistant"，能意图路由、按需跑 project pipeline、长跑任务进度回推群里，同时保持现有 chat/autonomous 两种 session mode 和 pipeline/assistant/coordinator 三类角色零影响。

## What Changes

- 新增 role `clawbot`（`agents/clawbot.md`），作为第三方 chat 的顶层 agent。**本质是 coordinator 变体**：同样吃 `spawn_agent` 工具派发子任务，但额外带一套意图路由元工具 + 独立 soul.md 加载层
- 新增 `SessionMode.bus_chat`，`_MODE_TO_ROLE["bus_chat"]="clawbot"`，`Gateway` 创建 session 时用新 mode。现有 `chat`/`autonomous` 两种 mode 不动
- 新增 `src/clawbot/` 模块容纳所有 clawbot 专属逻辑：factory（post-process patch soul）、prompt（bootstrap 文件加载 + runtime context tag）、session_state（pending_run 内存存储 + 90s TTL）、progress_reporter（订阅 EventBus 双写进群 + conversation）、tools/（7 个新工具）
- 新增 `config/clawbot/{SOUL,USER,TOOLS}.md` bootstrap 三件套，抄 nanobot 的 BOOTSTRAP_FILES 列表机制（存在就拼、不存在跳过），仅 clawbot factory 读取
- 新增 7 个 clawbot 专属工具，**project_id 显式参数**（不吃 tool_context）：`list_projects` / `get_project_info` / `search_project_docs` / `start_project_run` / `confirm_pending_run` / `cancel_pending_run` / `get_run_progress`
- 新增 `start_project_run` 两阶段提交机制：工具调用时不直接跑，写 `pending_run` slot，返回"待确认"。LLM 靠动态注入的 pending 上下文判断后续消息的确认/取消/覆盖意图。90s 超时静默清除
- 新增 pipeline run 进度回推机制：`ChatProgressReporter` 订阅 run EventBus，三条消息粒度（start / interrupt / done），双写到 outbound queue 和 conversation history，`[run #id]` 前缀区分并行 run
- **BREAKING (内部)**: `src/tools/builtins/spawn_agent.py` 加 `SUB_AGENT_DISALLOWED_ROLES = frozenset({"clawbot"})`，clawbot 不可被作为 spawn_agent 目标——防止其他 agent 递归调用群聊入口
- `src/bus/gateway.py` 创建 session 时 mode 从硬编码 `"assistant"` 改为 `"bus_chat"`；新增 Gateway 级 reporter registry `{run_id: ReporterTask}`，生命周期脱离 SessionRunner
- `src/engine/session_runner.py` `_build_agent_state` 加一行分派：role=clawbot → `create_clawbot_agent()`，其他走原有 `create_agent()`。这是 factory 外唯一 clawbot-aware 代码

## Capabilities

### New Capabilities
- `clawbot-agent`: ClawBot role 定义 + factory + soul bootstrap 加载机制 + SessionMode.bus_chat 接入 + runtime context 防注入注入
- `clawbot-routing-tools`: 7 个 clawbot 专属工具的参数协议、显式 project_id 语义、两档外的工具定位（元能力 / 自答 / 派工 / 跑项目）
- `clawbot-run-lifecycle`: start_project_run 两阶段提交（pending_run 内存槽 + 90s TTL + LLM 意图识别协议）+ ChatProgressReporter 订阅 + 双写协议 + Gateway 级 reporter registry 生命周期

### Modified Capabilities
- `session-runner`: 新增 `bus_chat` mode 到 `_MODE_TO_ROLE` 映射，`_build_agent_state` 按 role 分派 factory（clawbot 走 clawbot factory，其他走通用 factory）
- `session-manager`: `ChatSession.mode` 允许值扩展为 `{"chat", "autonomous", "bus_chat"}`
- `spawn-agent`: 新增 `SUB_AGENT_DISALLOWED_ROLES` 常量 + execute 入口早退检查，被拉黑的 role 调用时返回 `ToolResult(success=False)`

## Impact

- **新模块**: `src/clawbot/`（factory + prompt + session_state + progress_reporter + 7 tools）~800 行
- **新文件**: `agents/clawbot.md` + `config/clawbot/{SOUL,USER,TOOLS}.md` + 单测脚本
- **修改文件**: `src/bus/gateway.py`（mode 字段 + reporter registry）、`src/bus/session.py`（mode allowlist）、`src/engine/session_runner.py`（mode 映射 + factory 分派一行 if）、`src/tools/builtins/spawn_agent.py`（blacklist 常量 + 早退）
- **零影响**:
  - `src/agent/factory.py` / `context.py` / `loop.py` 零修改
  - `assistant` / `coordinator` / pipeline 节点 agent 完全不变
  - 现有 `search_docs` 工具（吃 tool_context.project_id）保留给 pipeline/assistant 用，clawbot 用新的 `search_project_docs` 两套并存
  - Discord/QQ/WeChat 三个 channel 适配器零修改
  - Gateway `/resume` 特殊路径零修改（用户 `/resume <run_id> approve` 仍然直达 pipeline 不走 SessionRunner）
- **兼容性**: 现有项目内 chat（`chat`/`autonomous` mode）和 pipeline REST 入口完全不受影响。第三方 chat 升级是加法，`bus_chat` 是新 mode 和现有 mode 并存
- **依赖**: 无新增外部依赖。nanobot 只是参考源码（`D:\github\hello-agents\nanobot\nanobot\agent\context.py:19` 的 BOOTSTRAP_FILES 模式），不是 runtime 依赖
