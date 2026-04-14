## Context

Phase 5 四模块（sandbox / hooks / permission / mcp）代码落地完整，但 permission 和 mcp 是"空壳兑现"：
- `src/permissions/` 模块齐全，`factory.create_agent` 也已构建 `PermissionChecker` 并通过 `register_permission_hooks` 注册为 `PRE_TOOL_USE` hook。但 `settings.permissions` 默认是 `{}`，`load_permission_rules({})` 返回空列表 → 实际没有规则落地，零拦截效果。
- `src/mcp/manager.py` 支持 stdio / http 两种 transport，`factory.create_agent` 的 `mcp_manager` 参数也已接入。但只有 `src/engine/pipeline.py` 会实例化 `MCPManager`；`src/engine/session_runner.py`（chat 路径）根本没构造 MCPManager，就算 settings 里配了 `mcp_servers` 也不会生效。

此外还有一个结构性漏洞：mas-pipeline 的 builtin tools 里**没有 `write_file`**。
- `src/tools/builtins/write_file.py` 是空文件，`__init__.py` 里也没注册。
- 写入型 agent（writer、assistant）现在只能通过 `shell` 间接写文件，而 `TOOL_CONTENT_FIELD["shell"] = "command"`，permission 规则只能对整条命令字符串做 glob —— LLM 用 `tee` / `python -c "open(...)"` / `sed -i` 都能绕过路径保护。
- 没有 `write_file` tool 就没法做"写路径白名单"，Permission 层的演示价值大打折扣。

现状基线（2026-04-14 实查）：
- 10 个 builtin tool：`read_file / shell / spawn_agent / web_search / memory_read / memory_write / search_docs / skill`（加上 spawn 时的隐藏 skill 机制）
- `TOOL_CONTENT_FIELD` 支持 `shell / write / read_file / edit / web_search` 五种字段匹配，其中 `write` 和 `edit` 指向 `file_path` 但**没有对应的实际 tool**
- `config/settings.yaml` 66 行，没有 `permissions:` / `mcp_servers:` 任何条目
- `agents/` 10 个角色：`writer` 只挂 `read_file`，`assistant` 挂 `web_search/search_docs/read_file/memory_*`，`general` 挂 `read_file/shell`

## Goals / Non-Goals

**Goals:**
- Permission 层从"空壳"变成"真拦截"：越权写入 `src/**` 被 deny，telemetry 里能看到 `permission_denied` 事件
- MCP github 从"未连接"变成"可调用"：researcher agent 能用 `github:search_repositories` / `github:get_file_contents` 做第二阶段检索
- 补齐 `write_file` builtin tool，让"路径白名单"有硬着陆的承载体
- 三个入口（chat / pipeline）都能享受到相同的 permission + mcp 配置，不分叉
- 给简历提供两条可量化话术："per-agent 写保护策略阻止 N 类越权路径" + "集成 MCP 生态，researcher agent 形成 web_search→github 二阶检索链"

**Non-Goals:**
- **Hooks 激活**：挪到简历 5.2 八股章节（telemetry 已覆盖"read"责任，hooks 要做的是"write 外部副作用"，本次不做 demo）
- **Sandbox 兑现**：只在面试口述，代码层不动
- **替换 shell 的命令过滤**：本次 shell 只补几条最明显的危险模式（`rm -rf *` / `sudo *` / `curl*|*sh`），不做穷举
- **LLM 查 DB 能力**：Q7 研究结论存档，本次不做任何只读 SQL MCP
- **多 MCP server**：只接 github 一个。`fetch` 等备选挪到后续 follow-up
- **Ask 模式响应器**：本次 deny 规则不用 `ask`，所以不碰 ask responder 机制
- **Permission 规则的动态热加载**：重启生效即可

## Decisions

### D1: 新建 `write_file` builtin tool，而不是改造 `shell` 走路径过滤

**选择**：新增一个 `WriteFileTool`，接收 `file_path` + `content` + 可选 `append` / `encoding`，直接写盘。

**替代方案**：
1. **只对 `shell` 加命令过滤** —— 拒。`echo x > /src/a.py`、`tee`、`python -c "open(...)"`、`sed -i` 四种姿势都能绕开单纯的 glob 命令匹配，安全承诺太弱
2. **用 `edit` tool（CC 风格的 old/new 替换）** —— 拒。语义过重，LLM 要读一次 + 改一次两次调用；mas-pipeline 的 writer 场景主要是生成新文件，不是增量编辑
3. **用 `patch` / `diff` tool** —— 拒。同样语义重，不是当前业务痛点

**理由**：`write_file` 是业界最通用的写入语义（CC / LangChain / LlamaIndex 全部支持），参数结构天然 `file_path`-first，直接能接 permission 的路径 glob，零脑力成本。

### D2: Permission 规则用"deny + 默认 allow"模式，不配 allow 列表

**选择**：settings 里只放 `deny:` 条目，不写 `allow:`；让 NORMAL 模式的"未命中规则即允许"兜底。

**替代方案**：
1. **显式 allow 列表**（CC 的 allowed_tools） —— 拒。会把"让 assistant 可以写 `projects/outputs/**`"变成"必须枚举每个允许路径"，维护成本高，容易漏掉合法路径
2. **strict 模式 + allow + ask** —— 拒。本次要展示的是"越权拦截"，不是"全覆盖 ACL"；strict 需要完整覆盖才能跑，超出本次目标

**理由**：deny-list 模式在"可信 agent + 少量禁区"场景下 ROI 最高，正好匹配 writer / assistant 的实际使用（允许自由写输出，只守住几个禁区）。简历话术也更好讲：**"防止 LLM 幻觉写坏 N 类关键路径"** 比 **"穷举 M 类允许路径"** 更抓眼球。

### D3: 禁区清单锁死在 7 类路径

**选择**（全部用 `write_file(<glob>)` 形式配置）：
- `agents/**` —— 防止 agent 改自己 / 改其他角色的定义
- `src/**` —— 防止改业务代码
- `config/**` —— 防止改配置（含 settings / pricing）
- `openspec/**` —— 防止改 spec / change 文档
- `.plan/**` —— 防止改 planning 笔记
- `pipelines/**` —— 防止改 pipeline YAML
- `skills/**` —— 防止改 skill 定义
- `.git/**` —— 防止改 git 内部
- `.env*` —— 防止写密钥
- `.claude/**` —— 防止改 CC 配置

**允许的安全区**（默认 allow 兜底）：
- `projects/*/outputs/**` —— pipeline 输出
- `uploads/**` —— 用户上传空间
- `/tmp/**` —— 临时文件
- 其他所有未被 deny 的路径

**理由**：这 7 类覆盖了"agent 幻觉改坏"的所有真实场景。10 类禁区对应的 glob 规则总数 ~10 条，permission check 的 O(N) 扫描成本完全可忽略。

### D4: Shell 命令黑名单只写 5 条"明显危险"模式

**选择**（全部用 `shell(<glob>)` 形式）：
- `shell(rm -rf *)` —— 防误删
- `shell(sudo *)` —— 防提权
- `shell(curl *|*sh*)` —— 防远程脚本执行（匹配 `curl ...|sh` 和 `curl ... | bash` 两种）
- `shell(git push *)` —— 防误推
- `shell(* > /etc/*)` —— 防写系统配置

**不做**：
- 穷举所有能写 `src/**` 的 shell 姿势（`tee`, `python -c`, `sed -i`, `cat >`, `> `, `>>`）—— 太碎，glob 覆盖不全，安全承诺容易被质疑
- 结构化命令解析（AST / bashlex） —— 超出本次范围

**理由**：承认 shell 的命令过滤是"纵深防御的第二层"，真正的路径保护靠 `write_file` 路径白名单来做。shell 黑名单只拦"明显会引起严重后果"的模式，面试时可以明说 "shell 的完备保护需要 structured command parser，本次用白名单 builtin tool + 黑名单 shell 双层策略"。

### D5: MCP GitHub 通过 stdio transport + `npx -y @modelcontextprotocol/server-github`

**选择**：stdio 模式，command=`npx`, args=`["-y", "@modelcontextprotocol/server-github"]`, env=`{GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_PAT}}`。

**替代方案**：
1. **自建 HTTP proxy 包一层** —— 拒。完全没价值，stdio 已经够用
2. **Clone 源码本地跑** —— 拒。`npx -y` 自动拉取 + 缓存，运维零成本

**理由**：`@modelcontextprotocol/server-github` 是官方维护的 TS 实现，npm registry 直接可用；docker 镜像里预装 `node` + `npx` 即可（compose 里的 app 容器已经有 node，因为前端 build 需要）。stdio 启动后常驻进程，MCPManager 在 session start 时连接、stop 时 kill。

**API 免费确认**：Github REST API 对 PAT 用户免费，rate limit 5000 req/hr，本次 demo 完全够用。MIT license。

### D6: MCPManager 实例从 pipeline 级提升到 "runtime 级 + per-session" 两档

**选择**：
- **Pipeline 路径**：沿用现状（`src/engine/pipeline.py` 每次 run 自建 MCPManager + start + shutdown）—— 不改
- **Session 路径**：`src/engine/session_runner.py` 在 `start()` 里 `self.mcp_manager = MCPManager(); await self.mcp_manager.start(settings.mcp_servers)`；`stop()` 里 `await self.mcp_manager.shutdown()`；`create_agent(mcp_manager=self.mcp_manager, ...)`

**替代方案**：
1. **全局单例 MCPManager** —— 拒。每个 session 起一个 npx 子进程有代价，但全局单例会让 "session 停了但 MCP 进程还在" 变成运维噩梦；且 MCPManager 的 `start()` 不是幂等的
2. **延迟到 create_agent 里惰性启动** —— 拒。MCP server 启动有 1-3 秒延迟，不应该阻塞第一次 tool call

**理由**：session-level lifecycle 把 MCP 子进程的生命周期和 session runner 绑定，用户关 chat → session stop → npx 被 kill，干净。代价是每个 session 起一个子进程（不是每次 tool call），可以接受。

**权衡**：如果将来 chat session 数量多到 npx 进程数成为问题，可以引入 "per-deployment mcp daemon" 模式（全局常驻 + 引用计数）—— 本次不做。

### D7: Researcher 拿 MCP github 权限，assistant / writer / general 拿 write_file 权限

**选择**（角色元数据改动）：

| 角色 | 新增 `tools:` 条目 | 新增 `mcp_servers:` 条目 |
|---|---|---|
| `researcher` | —— | `[github]` |
| `assistant` | `write_file` | —— |
| `writer` | `write_file` | —— |
| `general` | `write_file` | —— |
| `coordinator / parser / analyzer / exam_* / reviewer` | 不动 | 不动 |

**替代方案**：
1. **全角色都给 MCP github** —— 拒。researcher 是唯一有"外部信息检索"语义的角色，其他角色用不到；多余权限增加攻击面
2. **全角色都给 write_file** —— 拒。`parser / analyzer / reviewer` 的输出是上游报告，应该走 pipeline 的结构化 output，不是自由写盘

**理由**：最小权限原则。write_file 只给"生成型"agent，MCP github 只给"检索型"agent。简历话术："每个 agent 拿到完成任务最小必要工具集，permission 层兜底防幻觉"。

### D8: Smoke 测试脚本在现有 compose 栈里跑，不单独起进程

**选择**：`scripts/test_permission_mcp_smoke.py`，通过 REST API 触发：
1. 起一个 assistant session，prompt="请把'hello'写到 projects/1/outputs/smoke_test.txt" → 预期 success，文件落盘
2. 同一 session，prompt="请把'exploit'写到 src/exploit.py" → 预期 telemetry 出现 `permission_denied`，返回给 LLM 的 tool result 是拒绝原因
3. 起一个 researcher session，prompt="用 github search_repositories 搜 langgraph 最热的 3 个仓库" → 预期返回非空结果

**不做**：
- 单元测试替代 smoke —— 单元测试只能证明模块正确，不能证明集成落地
- Docker 容器内跑 pytest —— 用 REST 从外部触发更贴近真实调用链

**理由**：smoke 的价值是"端到端证明"，pytest 单元层已经覆盖细节。

## Risks / Trade-offs

- **[风险] GitHub PAT 泄漏** → 缓解：env var 注入，`.env*` 加入 write_file deny 清单（D3 已涵盖），`settings.local.yaml.example` 明确标注"不要 commit"
- **[风险] `npx -y` 首次启动慢（npm 拉包 3-10 秒）** → 缓解：compose build 阶段 `RUN npx -y @modelcontextprotocol/server-github --help || true` 预热缓存；失败也不阻塞，`MCPManager.start` 已有 "failed servers are logged and skipped" 兜底
- **[风险] 路径 glob 匹配被相对路径绕过**（LLM 传 `./src/../src/foo.py`） → 缓解：`WriteFileTool` 在参数 validation 里调 `os.path.realpath()` 规范化，再把规范化后的路径交给 permission 层
- **[风险] 简体中文 / Unicode 路径匹配** → fnmatch 支持 Unicode，但需验证；加一条单测覆盖中文路径
- **[风险] Permission 规则对 existing pipeline run 的反向兼容性** —— pipeline 现在用 NORMAL 模式 + 空 rules 跑，本次 rules 变非空后，现有管线如果隐式用 shell 往 `src/**` 写会立刻报 deny → 缓解：跑完 smoke 后手动 `blog_generation` / `blog_with_review` / `courseware_exam` 三条线冒烟验证；如有 agent 需要写到受保护路径，改走 `projects/outputs/`
- **[trade-off] write_file 走 path glob，不做 content scanning** —— 简历可写"路径级 ACL"，但不能宣称"内容级防泄漏"。承认这是分层防御的一层而已。

## Migration Plan

1. 先补 `write_file` tool + 注册 + `TOOL_CONTENT_FIELD` 扩展（纯增量，不动现有代码路径）
2. 跑现有 pytest 全量确认没破坏（write_file 是新增，不影响旧测试）
3. 改 agent 元数据 + settings.yaml 加配置
4. 改 session_runner.py 挂 MCPManager（pipeline 路径已经有，参考抄）
5. 补单元测试 + smoke 脚本
6. 起 compose + 跑 smoke + 三条 pipeline 反向兼容验证
7. 更新 `.plan/progress.md` + 勾掉 `.plan/wrap_up_checklist.md` 4.1

**Rollback**：所有改动都是增量配置 + 新文件，回滚只需 `git revert`。Permission 规则如果误伤正常管线，临时 workaround 是在 `config/settings.local.yaml` 的 `permissions.deny` 里删对应条目重启生效。

## Open Questions

- ~~write_file 是否支持 append 模式？~~ → 支持，`append: bool = False` 参数，默认覆盖写
- ~~write_file 是否要防止路径逃逸（`../`）？~~ → 是，`realpath` 规范化后再交给 permission
- ~~GitHub MCP server 需要哪些 scope？~~ → `public_repo` 就够（只读公开仓库 + search）
- ~~researcher 的 `mcp_servers: [github]` 是否需要在 assistant 里也加？~~ → 不加。assistant 保持 web_search 为主检索通道，researcher 才是"深度检索"角色
