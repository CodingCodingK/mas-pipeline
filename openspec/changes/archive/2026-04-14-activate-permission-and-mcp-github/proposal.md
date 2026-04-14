## Why

Phase 5 的四个模块（sandbox / hooks / permission / mcp）代码都已落地，但 **permission 和 mcp 是"空挂"状态**：工厂层有分支但 `settings.permissions` / `settings.mcp_servers` 是空字典，SessionRunner 也没实例化 MCPManager。这两个模块是简历上的核心卖点之一（"per-agent 写保护 + 外部工具生态接入"），必须做到"跑一次能看到效果"。

同时发现一个前置问题：`src/tools/builtins/write_file.py` 是空文件，根本没有 `write_file` builtin tool。原本设计的"写入路径白名单"根本无处可落——LLM 只能通过 `shell` 间接写文件，路径保护非常容易被绕过（`tee` / `python -c` / 重定向）。补齐这个基础 tool 是本次的先决条件。

## What Changes

- **新增 `write_file` builtin tool**（`src/tools/builtins/write_file.py`）—— 接收 `file_path` + `content`（可选 `append` / `encoding`），写入文件并返回字节数。是 permission 路径白名单的承载体。
- **扩展 `TOOL_CONTENT_FIELD`**：加入 `"write_file": "file_path"`，让 permission 规则能对 write_file 调用做 glob 路径匹配。
- **分配 write_file 工具给写入型 agent**：`writer` / `assistant` / `general` 三个角色的 `tools:` 列表加入 `write_file`。
- **Permission 规则落到 `config/settings.yaml`**：
  - `deny`: `write_file(agents/**)`, `write_file(src/**)`, `write_file(config/**)`, `write_file(openspec/**)`, `write_file(.plan/**)`, `write_file(pipelines/**)`, `write_file(skills/**)`, `write_file(.git/**)`, `write_file(.env*)`, `write_file(.claude/**)`
  - `deny`: `shell(rm -rf *)`, `shell(* > /etc/*)`, `shell(curl * | *sh)`, `shell(sudo *)`, `shell(git push *)` —— 堵住 shell 绕过路径保护的明显姿势
  - 不配 `allow`，走 NORMAL 模式的"未命中即允许"默认
- **MCP GitHub server 接入**：
  - `config/settings.yaml` 加 `mcp_servers.github`（stdio 模式，`npx -y @modelcontextprotocol/server-github`，env 里带 `GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_PAT}`）
  - `config/settings.local.yaml.example` 新增 `GITHUB_PAT` 占位说明
  - `researcher` 角色元数据加 `mcp_servers: [github]`，拿到 `github:search_repositories` / `github:get_file_contents` 等工具
- **SessionRunner 挂 MCPManager**：`src/engine/session_runner.py` 在 `start()` 里 `MCPManager().start(settings.mcp_servers)`，`stop()` 里 `shutdown()`，并把 manager 传进 `create_agent(mcp_manager=...)`
- **REST smoke 脚本**：`scripts/test_permission_mcp_smoke.py`——在干净 compose 栈里起一个 assistant session，依次触发「合法 write_file 到 `projects/outputs/` → 成功」「越权 write_file 到 `src/foo.py` → telemetry 出现 `permission_denied`」「researcher 调 github search → 返回真实结果」三条断言。
- **非目标**（明确不做）：Hooks 激活（挪到简历 5.2 纯八股）、Discord smoke、LLM 查 DB MCP、sandbox 兑现。

## Capabilities

### New Capabilities

- `write-file-tool`: A builtin tool that writes text content to a file path, subject to permission layer rules. Handles dir creation, append mode, encoding.
- `mcp-github-integration`: Lifecycle + config wiring that starts the `@modelcontextprotocol/server-github` MCP server from SessionRunner and exposes its tools to selected agent roles.

### Modified Capabilities

- `tool-builtins`: add `write_file` to the builtin registry alongside `read_file / shell / memory_* / search_docs / web_search / spawn_agent`.
- `permission-rules`: extend `TOOL_CONTENT_FIELD` with `write_file → file_path` so path-glob rules can match write_file calls.
- `permission-integration`: specify that `config/settings.yaml` ships a default non-empty `permissions:` block (deny-only) and that NORMAL mode is the default for chat sessions.
- `session-runner`: require SessionRunner to own an `MCPManager` lifecycle (start on `start()`, shutdown on `stop()`) and pass it into `create_agent`.
- `agent-factory`: clarify that when `mcp_manager` is provided and a role lists `mcp_servers`, only that subset is registered (no default-all fallback for chat roles).

## Impact

**Code**
- `src/tools/builtins/write_file.py` — new tool class, ~80 lines
- `src/tools/builtins/__init__.py` — import + register
- `src/permissions/types.py` — one-line `TOOL_CONTENT_FIELD` addition
- `src/engine/session_runner.py` — MCPManager lifecycle + `create_agent(mcp_manager=...)` plumb
- `agents/writer.md`, `agents/assistant.md`, `agents/general.md` — add `write_file` to tools list
- `agents/researcher.md` — add `mcp_servers: [github]`

**Config / ops**
- `config/settings.yaml` — new `permissions` + `mcp_servers` sections
- `config/settings.local.yaml.example` — `GITHUB_PAT` placeholder + instructions
- Docker operators must provision `GITHUB_PAT` env var (github.com PAT, `public_repo` scope is enough)

**Tests**
- Unit: `tests/tools/test_write_file.py` (existing path / new dir / append / denied path translated into friendly error)
- Unit: `tests/permissions/test_write_file_path_rules.py` (glob match, deny surface area)
- Smoke: `scripts/test_permission_mcp_smoke.py` (end-to-end via REST)

**Blast radius**
- Existing agents that did NOT have `write_file` are unaffected.
- New permission deny rules only fire on `write_file` + specific `shell` patterns; other tool calls pass through untouched.
- MCPManager start failure is already logged-and-skipped (no hard dep on GitHub PAT being present) — ships safe default for contributors without a token.

**Documentation**
- `.plan/progress.md` — add 收尾 4.1 完成条目
- `.plan/wrap_up_checklist.md` — 勾掉 4.1
