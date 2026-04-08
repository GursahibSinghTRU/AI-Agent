-- =============================================================================
-- TRU Risk & Safety Assistant — Oracle 23ai Schema
-- Run this in SQL Developer before starting the application.
-- =============================================================================

-- Sessions: one row per browser session
CREATE TABLE chat_sessions (
    id                VARCHAR2(36)                    NOT NULL,
    started_at        TIMESTAMP WITH TIME ZONE        DEFAULT SYSTIMESTAMP,
    last_activity_at  TIMESTAMP WITH TIME ZONE        DEFAULT SYSTIMESTAMP,
    total_messages    NUMBER(10)                      DEFAULT 0,
    CONSTRAINT pk_chat_sessions PRIMARY KEY (id)
);

-- Interactions: one row per user message / assistant response pair
CREATE TABLE chat_interactions (
    id                VARCHAR2(36)                    NOT NULL,
    session_id        VARCHAR2(36),
    created_at        TIMESTAMP WITH TIME ZONE        DEFAULT SYSTIMESTAMP,
    latency_ms        NUMBER(10)                      DEFAULT 0,
    prompt_tokens     NUMBER(10)                      DEFAULT 0,
    completion_tokens NUMBER(10)                      DEFAULT 0,
    user_feedback     NUMBER(2)                       DEFAULT 0,  -- 1=up, -1=down, 0=none
    CONSTRAINT pk_chat_interactions PRIMARY KEY (id),
    CONSTRAINT fk_interaction_session
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);

CREATE INDEX idx_interactions_session ON chat_interactions(session_id);
CREATE INDEX idx_interactions_created ON chat_interactions(created_at);
CREATE INDEX idx_sessions_started     ON chat_sessions(started_at);

-- =============================================================================
-- RAG Knowledge Base: document chunks with vector embeddings
-- Dimension 768 matches nomic-embed-text output.
-- Re-run ingest.py after creating this table to populate it.
-- =============================================================================

CREATE TABLE doc_chunks (
    id         VARCHAR2(64)                    NOT NULL,   -- SHA-256 content hash
    filename   VARCHAR2(255),
    page_num   NUMBER,
    title      VARCHAR2(500),
    chunk_text CLOB                            NOT NULL,
    embedding  VECTOR(768, FLOAT32),
    created_at TIMESTAMP WITH TIME ZONE        DEFAULT SYSTIMESTAMP,
    CONSTRAINT pk_doc_chunks PRIMARY KEY (id)
);

-- IVF-style approximate nearest-neighbour index (cosine distance)
-- NOTE: Oracle requires at least one row in the table before this index
-- can be built with NEIGHBOR PARTITIONS. Run ingest.py first, then:
--   EXEC DBMS_VECTOR.CREATE_VECTOR_INDEX('idx_doc_chunks_emb', 'doc_chunks', 'embedding', ...);
-- Or simply let Oracle use an exact (brute-force) scan until the index is built.
CREATE VECTOR INDEX idx_doc_chunks_emb ON doc_chunks(embedding)
    ORGANIZATION NEIGHBOR PARTITIONS
    DISTANCE COSINE
    WITH TARGET ACCURACY 95;
