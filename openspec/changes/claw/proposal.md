## Why

系统需要接入 Discord / QQ / WeChat 等外部通讯平台，让用户通过聊天软件直接与 Agent 交互。当前系统只能通过 API 调用或 pipeline 触发，缺少面向终端用户的实时对话入口。原 Phase 5.5 "Event Bus" 经调研 nanobot 项目后，确认核心需求是平台集成而非 pub-sub 消息总线。

## What Changes

- 新增 `MessageBus`：两个 asyncio.Queue（inbound + outbound），作为平台与系统的解耦层
- 新增 `InboundMessage` / `OutboundMessage` 协议无关消息类型，平台差异通过 metadata dict 携带
- 新增 `BaseChannel` ABC：统一平台适配器接口（start / stop / send / _handle_message）
- 新增三个平台适配器：Discord（WebSocket Gateway + REST）、QQ（qq-botpy 官方 SDK）、WeChat（ilinkai HTTP 长轮询）
- 新增 `ChannelManager`：管理所有 channel 生命周期，消费 outbound queue 分发回平台
- 新增 `Gateway`：消费 inbound queue，per-message 调度 agent_loop，管理 session
- 新增 `ChatSession` 模型（PostgreSQL）：外部平台会话到内部 Conversation 的映射
- 新增 ChatSession Redis 缓存层：热路径避免每条消息查 PG
- 扩展 `session/manager.py`：新增 ChatSession CRUD + Redis 缓存函数
- 扩展 `Settings`：新增 channels 配置段（per-channel token/secret + 全局 project_id）
- 新增 `gateway` CLI 入口：启动所有 channel + gateway 主循环

## Capabilities

### New Capabilities
- `message-bus`: MessageBus 双队列 + InboundMessage/OutboundMessage 消息类型
- `channel-adapter`: BaseChannel ABC + ChannelManager + Discord/QQ/WeChat 三个适配器
- `chat-gateway`: Gateway 主循环 + ChatSession 会话管理 (Redis+PG) + agent_loop 调度

### Modified Capabilities
- `session-manager`: 扩展支持 ChatSession CRUD + Redis 缓存（现有 Conversation/AgentSession 不变）

## Impact

- **新增依赖**：`websockets`（Discord）、`qq-botpy` + `aiohttp`（QQ）、`pycryptodome`（WeChat 媒体加解密）
- **新增 DB 表**：`chat_sessions`
- **新增代码目录**：`src/bus/`、`src/channels/`
- **现有模块影响极小**：不改 agent_loop、不改 pipeline、不改 coordinator。Gateway 调用现有 create_agent + run_agent_to_completion，聊天模式是独立路径
- **配置扩展**：settings.yaml 新增 channels 段，不影响现有配置
