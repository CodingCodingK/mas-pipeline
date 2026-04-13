-- mas-pipeline database initialization
-- Run automatically by PostgreSQL on first container start

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- users
-- ============================================================
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255),
    config      JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- projects
-- ============================================================
CREATE TABLE projects (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    pipeline    VARCHAR(255) NOT NULL,
    config      JSONB DEFAULT '{}',
    status      VARCHAR(50) DEFAULT 'active',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_projects_user ON projects(user_id);
CREATE INDEX idx_projects_status ON projects(status);

-- ============================================================
-- conversations (cross-run user conversation history)
-- ============================================================
CREATE TABLE conversations (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    messages    JSONB DEFAULT '[]',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_conversations_project ON conversations(project_id);

-- ============================================================
-- workflow_runs (one per pipeline execution instance)
-- ============================================================
CREATE TABLE workflow_runs (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id  INTEGER REFERENCES conversations(id),
    run_id      VARCHAR(255) UNIQUE NOT NULL,
    pipeline    VARCHAR(255),
    status      VARCHAR(50) DEFAULT 'pending',
    started_at  TIMESTAMP,
    finished_at TIMESTAMP,
    metadata    JSONB DEFAULT '{}'
);
CREATE INDEX idx_runs_project ON workflow_runs(project_id);
CREATE INDEX idx_runs_status ON workflow_runs(status);
CREATE INDEX idx_runs_run_id ON workflow_runs(run_id);

-- ============================================================
-- agent_runs (audit records for sub-agent executions)
-- ============================================================
CREATE TABLE agent_runs (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    role        VARCHAR(255) NOT NULL,
    description TEXT,
    status      VARCHAR(50) DEFAULT 'running',
    owner       VARCHAR(255),
    result      TEXT,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_agent_runs_run ON agent_runs(run_id);
CREATE INDEX idx_agent_runs_status ON agent_runs(status);

-- ============================================================
-- memories (project-scoped)
-- ============================================================
CREATE TABLE memories (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id),
    scope       VARCHAR(50) NOT NULL,
    type        VARCHAR(50) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description VARCHAR(500) NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_memories_project ON memories(project_id);
CREATE INDEX idx_memories_type ON memories(type);

-- ============================================================
-- documents (project-scoped file registry)
-- ============================================================
CREATE TABLE documents (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    filename    VARCHAR(500) NOT NULL,
    file_type   VARCHAR(50) NOT NULL,
    file_path   VARCHAR(1000),
    file_size   BIGINT,
    chunk_count INTEGER DEFAULT 0,
    parsed      BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_documents_project ON documents(project_id);

-- ============================================================
-- document_chunks (pgvector embeddings)
-- ============================================================
CREATE TABLE document_chunks (
    id          SERIAL PRIMARY KEY,
    doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB DEFAULT '{}'
);
CREATE INDEX idx_chunks_doc ON document_chunks(doc_id);
-- IVFFlat index requires rows to exist first; create after initial data load
-- CREATE INDEX idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops);

-- ============================================================
-- agent_sessions (hot in Redis, cold archive here)
-- ============================================================
CREATE TABLE agent_sessions (
    id          VARCHAR(255) PRIMARY KEY,
    run_id      INTEGER REFERENCES workflow_runs(id) ON DELETE SET NULL,
    agent_role  VARCHAR(255),
    messages    JSONB NOT NULL DEFAULT '[]',
    summary     TEXT,
    token_count INTEGER,
    created_at  TIMESTAMP DEFAULT NOW(),
    archived_at TIMESTAMP
);
CREATE INDEX idx_agent_sessions_run ON agent_sessions(run_id);

-- compact_summaries table removed in align-compact-with-cc: compact
-- summaries are now persisted inline in conversations.messages with
-- metadata.is_compact_summary=true, matching Claude Code's design.
DROP TABLE IF EXISTS compact_summaries CASCADE;

-- ============================================================
-- chat_sessions
-- ============================================================
CREATE TABLE chat_sessions (
    id              SERIAL PRIMARY KEY,
    session_key     VARCHAR(500) UNIQUE NOT NULL,
    channel         VARCHAR(50) NOT NULL,
    chat_id         VARCHAR(255) NOT NULL,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    mode            VARCHAR(20) NOT NULL DEFAULT 'chat',
    metadata        JSONB DEFAULT '{}',
    status          VARCHAR(50) DEFAULT 'active',
    created_at      TIMESTAMP DEFAULT NOW(),
    last_active_at  TIMESTAMP DEFAULT NOW(),
    CHECK (mode IN ('chat', 'autonomous'))
);
CREATE INDEX idx_chat_sessions_channel ON chat_sessions(channel);
CREATE INDEX idx_chat_sessions_project ON chat_sessions(project_id);

-- ============================================================
-- telemetry_events — Phase 6.2 polymorphic single-table store
-- ============================================================
CREATE TABLE telemetry_events (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type   TEXT NOT NULL,
    project_id   INTEGER NOT NULL,
    run_id       TEXT,
    session_id   INTEGER,
    agent_role   TEXT,
    payload      JSONB NOT NULL
);
CREATE INDEX idx_telemetry_run_ts ON telemetry_events(run_id, ts) WHERE run_id IS NOT NULL;
CREATE INDEX idx_telemetry_session_ts ON telemetry_events(session_id, ts) WHERE session_id IS NOT NULL;
CREATE INDEX idx_telemetry_event_ts ON telemetry_events(event_type, ts);
CREATE INDEX idx_telemetry_project_ts ON telemetry_events(project_id, ts);
CREATE INDEX idx_telemetry_payload_gin ON telemetry_events USING GIN (payload);

-- ============================================================
-- user_notify_preferences — Phase 6.3 per-user per-event channel selection
-- ============================================================
CREATE TABLE user_notify_preferences (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    channels   JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, event_type)
);
CREATE INDEX idx_user_notify_prefs_user ON user_notify_preferences(user_id);

-- ============================================================
-- Seed: default user
-- ============================================================
INSERT INTO users (name, email, config) VALUES
    ('default', 'admin@mas-pipeline.local', '{"role": "admin"}');
