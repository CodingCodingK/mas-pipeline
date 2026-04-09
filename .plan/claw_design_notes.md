# Claw (Channel Layer) 设计笔记

> Phase 5.5 — 外部通讯平台集成（原 Event Bus，重定义为 Channel Layer）

## 背景

原 plan 中 5.5 叫 "Event Bus"，目标是做 pub-sub 消息总线。经过调研 nanobot 项目后，发现：
1. 真正的需求不是 Event Bus，而是**接入 Discord / QQ / WeChat 等外部通讯平台**
2. nanobot 的 MessageBus 本质是两个 asyncio.Queue（inbound + outbound），不是 pub-sub
3. CC 的 commandQueue 也是普通 FIFO，不是 EventBus

因此将 5.5 从 "Event Bus" 重定义为 **"Claw"（Channel Layer）**，聚焦外部平台集成。

## 设计决策

### D1: MessageBus = 两个 asyncio.Queue

```python
class MessageBus:
    inbound:  asyncio.Queue[InboundMessage]   # 平台 → 系统
    outbound: asyncio.Queue[OutboundMessage]  # 系统 → 平台
```

不做 pub-sub、不做 topic 路由。nanobot 验证了这个方案在 12+ 平台上工作良好。

### D2: 与现有 notification_queue 共存

- `notification_queue`（AgentState 上）：coordinator_loop 内部调度，spawn_agent 完成通知
- `MessageBus`：外部平台消息收发

两者性质不同，不合并。Gateway 消费 MessageBus.inbound 后，走独立的处理路径。

### D3: 三个平台适配器

| 平台 | 方案 | 连接方式 | 依赖 |
|------|------|----------|------|
| Discord | Bot API | WebSocket Gateway + REST | `websockets` + `httpx` |
| QQ | 官方机器人 SDK | WebSocket (botpy 内置) | `qq-botpy` + `aiohttp` |
| WeChat | ilinkai 个人微信 API | HTTP 长轮询 | `httpx` + `pycryptodome` |

参考来源：nanobot 项目（D:\github\hello-agents\nanobot），已验证可行。

#### Discord 细节
- WebSocket 连接 Discord Gateway，处理 MESSAGE_CREATE 等事件
- REST API 发送消息（POST /channels/{id}/messages）
- 需要 Bot Token + MESSAGE CONTENT INTENT 权限

#### QQ 细节
- 使用 `qq-botpy` 官方 SDK，WebSocket 接收事件
- 支持 C2C 私聊 + 群聊（群聊需 @机器人）
- 需要 AppID + AppSecret（QQ 开放平台申请）

#### WeChat 细节
- 通过 ilinkai API（`https://ilinkai.weixin.qq.com`）接入个人微信
- HTTP 长轮询获取消息（35s timeout）
- 媒体文件 AES-128-ECB 加解密
- 首次需扫码登录，token 持久化后免扫码
- 逆向协议（源自 @tencent-weixin/openclaw-weixin），非官方 API

### D4: Gateway 架构 — per-message dispatch

```
InboundMessage
     ↓
Gateway.run()
     ↓
SessionManager.resolve(session_key)
     ├─ Redis 缓存命中 → 拿到 conversation_id + project_id
     └─ 未命中 → PG 查/创建 ChatSession + Conversation
     ↓
加载历史: get_messages(conversation_id)
     ↓
创建 agent → agent_loop(history + 当前消息) → response
     ↓
追加消息到 Conversation (PG)
     ↓
publish_outbound(response) → ChannelManager → 对应平台
```

关键设计：**每条消息是一次独立的 agent_loop 调用**，不用长驻 coordinator。
对话连续性靠 Session 保存历史实现。与 nanobot 的 `_process_message` 模式一致。

### D5: Session 设计 — Redis 热缓存 + PostgreSQL 持久化

#### 复用现有模块

| 现有模块 | 复用方式 |
|----------|---------|
| `Conversation` 模型 | 一个 ChatSession 对应一个 Conversation，消息存 messages JSONB |
| `session/manager.py` | 复用 append_message / get_messages / clean_orphan_messages |
| `WorkflowRun.session_id` | 聊天触发 pipeline 时填入 ChatSession.id，串联两个世界 |
| `get_redis()` / `get_db()` | 直接用现有连接层 |

#### 新增模型

```python
class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id              # PK
    session_key     # unique, "discord:123456"
    channel         # "discord" / "qq" / "wechat"
    chat_id         # 平台侧原始会话 ID
    project_id      # FK → projects.id
    conversation_id # FK → conversations.id
    metadata_       # JSONB, 平台特有数据
    status          # "active" / "archived"
    created_at
    last_active_at
```

#### 三层存储

```
Redis (热路径)
  chat_session:{key} → {session_id, project_id, conversation_id}
  TTL = 24h，每次消息刷新
       │
       ▼ miss
PostgreSQL (持久层)
  chat_sessions 表 → session_key 到 conversation_id 的映射
  conversations 表 → messages JSONB 聊天记录
```

## 架构总览

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│ Discord  │  │    QQ    │  │  WeChat  │
│ WS+REST  │  │ qq-botpy │  │ 长轮询    │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │
     ▼             ▼             ▼
  BaseChannel (ABC: start/stop/send/_handle_message)
     │
     ▼
┌──────────────────────────────────────────┐
│  MessageBus (inbound + outbound Queue)   │
└──────┬────────────────────────┬──────────┘
       │                        ▲
       ▼                        │
┌──────────────────┐     publish_outbound
│     Gateway      │            │
│                  │            │
│  SessionManager  │            │
│  (Redis + PG)    │            │
│       ↓          │            │
│  agent_loop()    │────────────┘
│       ↓          │
│  save to PG      │
└──────────────────┘
```

## Nanobot 参考对比

| 维度 | nanobot | mas-pipeline |
|------|---------|-------------|
| MessageBus | 两个 asyncio.Queue | 同 |
| 平台适配 | BaseChannel ABC, 12+ 适配器 | BaseChannel ABC, 3 适配器 |
| Session 存储 | JSONL 文件 | Redis 缓存 + PostgreSQL |
| 历史浓缩 | LLM 总结 → MEMORY.md + HISTORY.md | 后续可接 compact 模块 |
| ID 映射 | 隐式 channel:chat_id | 同概念，ChatSession 表显式存储 |
| 多项目 | 不支持，一个 gateway = 一个 agent | 一个 gateway = 一个 project_id |
| Pipeline 触发 | 无 | ChatSession.id → WorkflowRun.session_id |
| Config | JSON config per channel | settings.yaml channels 段 |

## 文件结构预览

```
src/bus/
├── __init__.py
├── message.py       # InboundMessage / OutboundMessage 数据类
├── bus.py           # MessageBus (两个 asyncio.Queue)
├── gateway.py       # Gateway: consume inbound → session → agent → outbound
└── session.py       # ChatSession CRUD + Redis 缓存

src/channels/
├── __init__.py
├── base.py          # BaseChannel ABC
├── manager.py       # ChannelManager: 启动/停止所有 channel, dispatch outbound
├── discord.py       # Discord adapter
├── qq.py            # QQ adapter
└── wechat.py        # WeChat adapter
```

## 对现有模块的影响

| 模块 | 变更 | 说明 |
|------|------|------|
| `src/models.py` | 新增 ChatSession | 新表 |
| `src/session/manager.py` | 扩展 | 新增 ChatSession CRUD + Redis 缓存函数 |
| `src/project/config.py` | 扩展 | Settings 新增 channels 配置段 |
| `src/agent/factory.py` | 不变 | Gateway 直接调 create_agent |
| `src/agent/loop.py` | 不变 | Gateway 调 run_agent_to_completion |
| `src/engine/coordinator.py` | 不变 | 聊天模式不走 coordinator_loop |
| `src/engine/pipeline.py` | 不变 | Pipeline 模式独立 |
| `src/engine/run.py` | 微调 | create_run 时可选填 session_id |

核心原则：**聊天模式是新路径，不改现有 pipeline/coordinator 路径**。

## 实现详情

### 完成日期: 2026-04-09

### 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `src/bus/__init__.py` | ~3 | 模块初始化 |
| `src/bus/message.py` | ~33 | InboundMessage / OutboundMessage 数据类 |
| `src/bus/bus.py` | ~32 | MessageBus，两个 asyncio.Queue |
| `src/bus/session.py` | ~146 | ChatSession CRUD + Redis 缓存层 |
| `src/bus/gateway.py` | ~156 | Gateway 主循环 + per-session 并发控制 |
| `src/bus/cli.py` | ~80 | CLI 入口 + 优雅停机 |
| `src/channels/__init__.py` | ~3 | 模块初始化 |
| `src/channels/base.py` | ~69 | BaseChannel ABC |
| `src/channels/manager.py` | ~122 | ChannelManager 生命周期管理 |
| `src/channels/discord.py` | ~184 | Discord WebSocket Gateway + REST |
| `src/channels/qq.py` | ~152 | QQ qq-botpy SDK 适配 |
| `src/channels/wechat.py` | ~205 | WeChat ilinkai HTTP 长轮询 |

### 修改的现有文件

| 文件 | 变更 |
|------|------|
| `src/models.py` | 新增 ChatSession ORM 模型 |
| `src/project/config.py` | 新增 ChannelsConfig 配置类 |
| `scripts/init_db.sql` | 新增 chat_sessions 表 + 索引 |

### 测试覆盖

| 测试文件 | 测试数 | 覆盖内容 |
|---------|--------|----------|
| `test_claw_message.py` | 21 | InboundMessage / OutboundMessage 字段、session_key、隔离性 |
| `test_claw_bus.py` | 20 | publish/consume、FIFO、阻塞、超时、队列独立性 |
| `test_claw_base_channel.py` | 20 | _handle_message 发布、metadata 转发、类型强转 |
| `test_claw_channel_manager.py` | 19 | 启停生命周期、禁用跳过、dispatch 路由、容错 |
| `test_claw_session.py` | 25 | Redis 命中/未命中、PG 回退、创建新建、刷新、历史加载 |
| `test_claw_gateway.py` | 16 | 端到端 mock、错误处理、per-session 串行、跨 session 并发 |
| `test_claw_discord.py` | 41 | WebSocket HELLO→IDENTIFY、MESSAGE_CREATE、REST 发送、分割、限流 |
| `test_claw_qq.py` | 33 | C2C/群聊事件、去重 LRU、send 路由、容错 |
| `test_claw_wechat.py` | 47 | 长轮询、context_token、发送分割、token 持久化、auth headers |
| **总计** | **242** | |

### 关键实现决策

1. **ChannelManager 延迟注册**: `_register_channels()` 使用 try/except ImportError，缺依赖不阻塞启动
2. **Discord 重连**: `start()` 外层 while 循环，ConnectionClosed 后 5s 重连，支持 RESUME 恢复序列号
3. **QQ 去重**: OrderedDict 作 LRU 缓存（1000 条），`_is_duplicate()` O(1) 查重 + 自动淘汰
4. **WeChat 状态持久化**: `~/.mas-pipeline/wechat/account.json` 保存 token + cursor + context_tokens，重启免登录
5. **Gateway 并发模型**: `asyncio.create_task` 实现跨 session 并发，`asyncio.Lock` per session_key 保证同 session 串行
6. **CLI 优雅停机**: 信号处理器 set `shutdown_event`，main 循环 `asyncio.wait` FIRST_COMPLETED 后执行 stop 链
