# TRU Chatbot - Privacy-First Analytics Database Handoff

Welcome to the TRU (Thompson Rivers University) AI Chatbot project! We're glad to have you on board.

This document contains everything you need to design and implement the database backend (using **Supabase / PostgreSQL**) for our chatbot analytics dashboard. 

## 1. Project Overview & Core Philosophy
We have a custom AI assistant deployed on our student-facing pages. Managing student data requires strict data governance. Therefore, our **number one rule** for this database architecture is a **Privacy-First Approach**:
**We DO NOT store raw user chat messages or the AI's actual text responses in the database.**

Instead, we only store **metadata, telemetry, and numerical vectors** that help us understand usage patterns, performance, and user satisfaction without compromising privacy.

The data you collect will power an internal analytics dashboard, tracking:
- How often the bot is used (hourly/daily usage heatmaps)
- Interaction volume (total messages per session)
- Performance metrics (response latency, token usage)
- User satisfaction (thumbs up / thumbs down feedback)

## 2. Tracking Requirements
Here is exactly what we need to track:

### Session-Level Metrics
- A unique identifier for the user's visit/chat session.
- When the session started and ended.
- **Total Messages Count**: The total number of back-and-forth messages (user prompts + agent replies) within that session.

### Interaction-Level Metrics (Per Message)
- A unique identifier for the interaction.
- The timestamp of when the AI responded.
- **Latency (ms)**: How long the backend took to generate the response.
- **Tokens**: How many `prompt_tokens` and `completion_tokens` were consumed.
- **Feedback**: Did the user click the "Helpful" (Thumbs Up) or "Unhelpful" (Thumbs Down) button on this specific response?

*(Note: We intentionally exclude tracking `client_device`, `page_url`, and the specific internal source documents the AI references, to keep the scope tight and privacy high.)*

---

## 3. Proposed Supabase (PostgreSQL) Schema
Below is the recommended relational database schema for Supabase. It uses UUIDs to handle relational mapping.

### Table 1: `chat_sessions`
Tracks the overarching conversation a user has with the bot.

```sql
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Tracks the total back-and-forth volume (User Messages + Agent Replies)
    total_messages INT DEFAULT 0,
    
    -- Useful for dashboard aggregations (e.g. Total Sessions Today)
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Table 2: `chat_interactions`
Tracks the metadata of an individual AI response.

```sql
CREATE TABLE chat_interactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
    
    -- Performance Metrics
    latency_ms INT NOT NULL,               -- Time taken to generate the response
    prompt_tokens INT DEFAULT 0,           -- Context size sent to LLM
    completion_tokens INT DEFAULT 0,       -- Length of AI response
    
    -- User Feedback (1 = Thumbs Up, -1 = Thumbs Down, 0 = No feedback)
    user_feedback SMALLINT DEFAULT 0,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexing for faster Analytics queries (Dashboard performance)
CREATE INDEX idx_interactions_session_id ON chat_interactions(session_id);
CREATE INDEX idx_interactions_created_at ON chat_interactions(created_at);
```

---

## 4. API & Data Flow Context
While you are writing the database logic, the frontend/backend developers will be wiring up the endpoints. Here is how the app expects to interact with your Supabase database:

1. **Session Initialization**: When a user opens the chat, the frontend generates a `session_id` (UUID). If that UUID doesn't exist in `chat_sessions`, the API should create a new row.
2. **Message Telemetry (Streaming)**: Our chatbot streams its answers via Server-Sent Events (SSE). Once the response finishes streaming, the Python backend will calculate the `latency_ms` and `tokens` and perform an `INSERT` into `chat_interactions`.
3. **Updating Total Messages**: Every time a user message is sent or an AI message is generated, the API will increment the `total_messages` counter on the active `chat_sessions` row.
4. **Capturing Feedback**: The frontend chat widget has hidden "Thumbs Up" and "Thumbs Down" buttons on every AI response. When clicked, it fires an async `fetch` request with the `interaction_id`. Your database needs an endpoint/function to simply `UPDATE chat_interactions SET user_feedback = 1 WHERE id = '...';`.

## 5. Dashboard Queries You Might Need to Write
To help you plan, here are the types of aggregations the dashboard will eventually ask for via Supabase RPCs or REST endpoints:

- **Usage Heatmaps**: Count of `chat_sessions` grouped by Day of the Week and Hour of the Day.
- **Average Interaction Latency**: `AVG(latency_ms)` grouped by day/week.
- **Feedback Ratio**: The count of positive vs. negative feedback over a timeline.
- **Engagement Depth**: `AVG(total_messages)` per session.

## Next Steps for You
1. Initialize the Supabase project and run the SQL schema migrations.
2. Set up Row Level Security (RLS). Ensure the API backend (via Service Role Key) has full access, but public anonymous access is restricted (since we do serverside inserts).
3. Let the backend team know when the tables are deployed so they can connect the Python API telemetry pipelines!