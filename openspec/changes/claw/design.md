## Context

系统已有完整的 Agent 执行链路（factory → agent_loop → tools → LLM），但只能通过代码调用或 pipeline YAML 触发。需要接入 Discord / QQ / WeChat 外部通讯平台，让终端用户通过聊天直接与 Agent 交互。

现有基础设施：
- `Conversation` 模型（PG，messages JSONB）+ `session/manager.py` CRUD
- `AgentSessionRecord`（Redis 热存 → PG 归档）
- `WorkflowRun.session_id` 字段已预留
- `get_redis()` / `get_db()` 连接层
- `create_agent()` + `run_agent_to_completion()` 完整调用链

参考项目：nanobot（D:\github\hello-agents\nanobot），已验证 MessageBus + BaseChannel 架构在 12+ 平台上工作良好。

## Goals / Non-Goals

**Goals:**
- 三个平台可用：Discord、QQ、WeChat，真实能跑通收发消息
- 统一 MessageBus 解耦平台协议与 Agent 处理逻辑
- ChatSession 映射外部会话到内部 Conversation，Redis 热缓存 + PG 持久化
- 一个 `gateway` 入口启动所有 channel + 消息处理循环
- 对现有 agent_loop / pipeline / coordinator 零侵入

**Non-Goals:**
- 不做 pub-sub / topic 路由 / 事件总线
- 不改现有 notification_queue（coordinator 内部调度机制，独立共存）
- 不做历史浓缩（compact 模块已有基础，后续对接）
- 不做多 project 路由（一个 gateway 实例 = 一个 project_id）
- 不做媒体文件处理（图片/视频/语音，后续扩展）
- 不做 SendMessage（Agent 间直接通信，后续扩展）

## Decisions

### D1: MessageBus = 两个 asyncio.Queue

**选择**：inbound Queue + outbound Queue，不做 pub-sub。

**替代方案**：
- Redis Pub/Sub — 跨进程，但单进程场景是过度工程
- 带 topic 的 EventBus — 只有一个消费者（Gateway），topic 路由没有消费者

**理由**：nanobot 用同样方案服务 12+ 平台，CC 的 commandQueue 也是普通 FIFO。消费者只有 Gateway 一个，pub-sub 没有意义。

### D2: per-message agent_loop，不用长驻 coordinator

**选择**：每条 inbound 消息触发一次 `create_agent → run_agent_to_completion`，对话连续性靠 Session 历史。

**替代方案**：
- 长驻 coordinator_loop — 需要保持 AgentState 在内存，复杂度高，资源浪费
- 改造 coordinator_loop 支持外部消息注入 — 侵入现有代码

**理由**：nanobot 的 `_process_message` 就是这个模式。聊天场景天然是请求-响应，不需要后台持续运行。Sub-agent 调度是 coordinator 的事，不是聊天的事。

### D3: ChatSession 模型 + Redis 缓存 + 复用 Conversation

**选择**：
- 新增 `ChatSession` PG 表：`session_key → conversation_id + project_id` 映射
- Redis 缓存：`chat_session:{key}` 存 session_id/project_id/conversation_id，TTL 24h
- 聊天记录直接写入已有 `Conversation.messages` JSONB

**替代方案**：
- JSONL 文件存储（nanobot 的做法）— 我们已有 PG + Redis，不需要文件
- 新建独立 messages 表 — Conversation 已有 messages JSONB，没必要重复

**理由**：最大化复用现有模块。`append_message` / `get_messages` / `clean_orphan_messages` 全部直接用。Redis 缓存避免每条消息查 PG 的 session_key → conversation_id 映射。

### D4: BaseChannel ABC 统一适配器接口

**选择**：参考 nanobot 的 BaseChannel 模式。

```
BaseChannel (ABC)
├── start() → 连接平台，监听消息
├── stop() → 断开连接
├── send(OutboundMessage) → 发送消息到平台
└── _handle_message() → 权限检查 + 构造 InboundMessage + publish to bus
```

三个实现：
- `DiscordChannel`：websockets 连 Gateway + httpx 发消息
- `QQChannel`：qq-botpy SDK，WebSocket 接收事件
- `WeChatChannel`：httpx 长轮询 ilinkai API

### D5: ChannelManager 管理生命周期 + outbound 分发

**选择**：ChannelManager 负责：
1. 根据 settings.yaml channels 配置启动/停止所有 enabled channel
2. 消费 MessageBus.outbound 队列，根据 `msg.channel` 路由到对应 adapter 的 `send()`

### D6: Gateway CLI 入口

**选择**：新增 `gateway` 命令作为独立入口，启动顺序：
1. 初始化 DB + Redis 连接
2. 创建 MessageBus
3. 启动 ChannelManager（所有 enabled channels）
4. 运行 Gateway 主循环（consume inbound → session → agent → outbound）

与 pipeline 入口完全独立，不改现有 run_coordinator / execute_pipeline。

### D7: 配置结构

```yaml
channels:
  project_id: 1
  role: "assistant"
  max_history: 50
  session_ttl_hours: 24
  discord:
    enabled: true
    token: "${DISCORD_BOT_TOKEN}"
  qq:
    enabled: true
    app_id: "${QQ_APP_ID}"
    secret: "${QQ_APP_SECRET}"
  wechat:
    enabled: true
    token: "${WECHAT_TOKEN}"
    base_url: "https://ilinkai.weixin.qq.com"
```

Token 支持环境变量引用，不在 YAML 明文存储。

## Risks / Trade-offs

- **[WeChat 稳定性]** ilinkai API 是逆向协议，非官方。→ 缓解：token 持久化减少重新登录频率，连接断开时自动重试
- **[QQ 官方 API 限制]** 群聊需要 @机器人触发。→ 缓解：C2C 私聊无此限制，群聊是 QQ 平台规则
- **[Conversation JSONB 膨胀]** 长期聊天 messages 数组会增长。→ 缓解：max_history 限制加载条数，后续可接 compact 浓缩
- **[per-message agent_loop 延迟]** 每条消息冷启动 agent。→ 缓解：create_agent 主要是内存操作（读 YAML + 构造 state），无 IO 瓶颈
- **[平台 SDK 依赖]** qq-botpy、websockets、pycryptodome 是新增外部依赖。→ 缓解：都是成熟库，pinned 版本
