## 1. ORM Models & Config

- [x] 1.1 Add ORM models to `src/models.py`: Conversation, AgentSessionRecord, Memory, CompactSummary
- [x] 1.2 Update `src/project/config.py` Settings: compact 百分比配置 (autocompact_pct, blocking_pct, micro_keep_recent) + context_windows 可选 dict
- [x] 1.3 Update `config/settings.yaml`: 替换旧 compact 绝对值为百分比配置

## 2. Session Manager

- [x] 2.0 Rename `user_sessions` table to `conversations` in `scripts/init_db.sql` + update `workflow_runs.session_id` FK + index name
- [x] 2.1 Implement `src/session/manager.py`: Conversation CRUD (create_conversation, get_conversation, append_message, get_messages) + ConversationNotFoundError
- [x] 2.2 Implement Agent Session Redis ops (create_agent_session, append_agent_message, get_agent_messages) with TTL
- [x] 2.3 Implement Agent Session archival (archive_agent_session: Redis → PG + delete Redis key)
- [x] 2.4 Implement `clean_orphan_messages(messages)` orphan tool_result cleanup
- [x] 2.5 Write `scripts/test_session_manager.py` verification script

## 3. Memory System

- [x] 3.1 Implement `src/memory/store.py`: write_memory, update_memory, delete_memory, list_memories, get_memory + MemoryNotFoundError + type validation
- [x] 3.2 Implement `src/memory/selector.py`: select_relevant with light-tier LLM judgment
- [x] 3.3 Implement `src/tools/builtins/memory.py`: MemoryReadTool + MemoryWriteTool
- [x] 3.4 Update `src/tools/builtins/__init__.py`: add memory_read + memory_write to get_all_tools()
- [x] 3.5 Update `src/agent/context.py`: _memory_layer accepts and renders memory_context parameter
- [x] 3.6 Write `scripts/test_memory_system.py` verification script

## 4. Compact

- [x] 4.1 Implement `src/agent/compact.py`: estimate_tokens, get_context_window (三级查找), get_thresholds, CompactThresholds dataclass, CompactResult dataclass
- [x] 4.2 Implement micro_compact(messages, keep_recent=3)
- [x] 4.3 Implement auto_compact(messages, adapter, model) with summary prompt + compact_summaries persistence
- [x] 4.4 Implement reactive_compact(messages, adapter, model) with aggressive split
- [x] 4.5 Write `scripts/test_compact.py` verification script

## 5. Agent Loop Integration

- [x] 5.1 Add TOKEN_LIMIT to ExitReason in `src/agent/state.py`
- [x] 5.2 Integrate compact into `src/agent/loop.py`: microcompact + autocompact + blocking_limit before LLM call
- [x] 5.3 Add reactive compact handling in `src/agent/loop.py`: catch context_length_exceeded, call reactive_compact
- [x] 5.4 Write `scripts/test_loop_compact.py` verification script for compact integration
