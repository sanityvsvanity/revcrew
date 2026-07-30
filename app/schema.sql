-- RevCrew schema: idempotent (CREATE TABLE IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS mock_crm_objects (
    id SERIAL PRIMARY KEY,
    type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mock_campaigns (
    id SERIAL PRIMARY KEY,
    campaign_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mock_messages (
    id SERIAL PRIMARY KEY,
    channel TEXT NOT NULL,
    ts TEXT,
    text TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approvals (
    run_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    reject_reason TEXT,
    reject_detail TEXT,
    edits JSONB NOT NULL DEFAULT '[]',
    push_status TEXT,
    push_detail JSONB,
    reminder_sent BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    retries INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Databases created before these columns existed need them added:
-- CREATE TABLE IF NOT EXISTS is a no-op on an existing table.
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS reject_reason TEXT;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS reject_detail TEXT;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS edits JSONB NOT NULL DEFAULT '[]';
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS push_status TEXT;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS push_detail JSONB;
ALTER TABLE approvals ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

CREATE TABLE IF NOT EXISTS write_audit (
    id SERIAL PRIMARY KEY,
    context_id TEXT NOT NULL,
    source TEXT NOT NULL,
    operation TEXT NOT NULL,
    object_type TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allowed', 'refused', 'deduped')),
    reason TEXT NOT NULL DEFAULT '',
    payload_summary JSONB NOT NULL DEFAULT '{}',
    result JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_write_audit_idempotency ON write_audit(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_write_audit_context ON write_audit(context_id);
CREATE INDEX IF NOT EXISTS idx_write_audit_created ON write_audit(created_at);

CREATE TABLE IF NOT EXISTS stage_cache (
    pipeline_id TEXT PRIMARY KEY,
    stages JSONB NOT NULL DEFAULT '[]',
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
