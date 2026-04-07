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
