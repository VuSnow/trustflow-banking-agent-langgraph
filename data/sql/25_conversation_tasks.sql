-- Durable task switching state for chatbot workflows.

ALTER TABLE chat_sessions
ADD COLUMN IF NOT EXISTS active_task_id UUID DEFAULT NULL;

CREATE TABLE IF NOT EXISTS conversation_tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(100) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(20) NOT NULL,
    task_type VARCHAR(50) NOT NULL DEFAULT 'UNKNOWN',
    operation VARCHAR(80),
    lifecycle VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (lifecycle IN ('active', 'suspended', 'completed', 'cancelled', 'expired')),
    fsm_state VARCHAR(50) NOT NULL DEFAULT 'idle',
    graph_thread_id VARCHAR(220) NOT NULL UNIQUE,
    pending_draft JSONB,
    response_data JSONB,
    last_user_message TEXT,
    last_agent_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversation_tasks_session_lifecycle
ON conversation_tasks(session_id, lifecycle, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_tasks_user_updated
ON conversation_tasks(user_id, updated_at DESC);
