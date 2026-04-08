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
    embedding   vector(1536),
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

-- ============================================================
-- compact_summaries
-- ============================================================
CREATE TABLE compact_summaries (
    id          SERIAL PRIMARY KEY,
    session_id  VARCHAR(255) NOT NULL,
    summary     TEXT NOT NULL,
    token_count INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_compact_session ON compact_summaries(session_id);

-- ============================================================
-- telemetry_events
-- ============================================================
CREATE TABLE telemetry_events (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR(255) NOT NULL,
    event_type      VARCHAR(100) NOT NULL,
    agent_id        VARCHAR(255),
    agent_role      VARCHAR(255),
    model           VARCHAR(255),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    thinking_tokens INTEGER,
    tool_name       VARCHAR(255),
    tool_params     JSONB,
    tool_success    BOOLEAN,
    latency_ms      INTEGER,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_telemetry_run ON telemetry_events(run_id);
CREATE INDEX idx_telemetry_type ON telemetry_events(event_type);
CREATE INDEX idx_telemetry_created ON telemetry_events(created_at);

-- ============================================================
-- Seed: default user
-- ============================================================
INSERT INTO users (name, email, config) VALUES
    ('default', 'admin@mas-pipeline.local', '{"role": "admin"}');
