-- F.I.R.E. Database Initialization
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUM TYPES
-- ============================================================
CREATE TYPE ticket_status AS ENUM (
    'new', 'ingested', 'pii_stripped', 'spam_checked',
    'analyzing', 'enriched', 'routed', 'closed'
);

CREATE TYPE ticket_type AS ENUM (
    'complaint', 'request', 'suggestion', 'question', 'other'
);

CREATE TYPE priority_level AS ENUM (
    'critical', 'high', 'medium', 'low'
);

CREATE TYPE processing_stage AS ENUM (
    'ingestion', 'pii_anonymization', 'spam_filter',
    'llm_analysis', 'sentiment_analysis', 'geocoding',
    'feature_engineering', 'priority_calculation', 'routing'
);

CREATE TYPE stage_status AS ENUM (
    'pending', 'in_progress', 'completed', 'failed', 'skipped'
);

-- ============================================================
-- MANAGERS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS managers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(50),
    competencies TEXT[] DEFAULT '{}',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geo_point GEOGRAPHY(POINT, 4326),
    max_tickets_per_day INT DEFAULT 20,
    current_load INT DEFAULT 0,
    stress_score DOUBLE PRECISION DEFAULT 0.0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TICKETS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS tickets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id VARCHAR(255),
    user_name VARCHAR(255),
    user_email VARCHAR(255),
    user_age INT,
    subject VARCHAR(500),
    body TEXT NOT NULL,
    body_anonymized TEXT,
    language VARCHAR(10),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geo_point GEOGRAPHY(POINT, 4326),
    address TEXT,
    attachment_urls TEXT[] DEFAULT '{}',
    ticket_type ticket_type DEFAULT 'other',
    status ticket_status DEFAULT 'new',
    priority priority_level,
    priority_score DOUBLE PRECISION,
    is_spam BOOLEAN DEFAULT FALSE,
    spam_probability DOUBLE PRECISION DEFAULT 0.0,
    text_length INT,
    text_length_times_age DOUBLE PRECISION,
    id_count_of_user INT DEFAULT 0,
    assigned_manager_id UUID REFERENCES managers(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- AI ANALYSIS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS ai_analysis (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    detected_type ticket_type,
    detected_language VARCHAR(10),
    summary TEXT,
    summary_anonymized TEXT,
    sentiment_score DOUBLE PRECISION,
    sentiment_label VARCHAR(50),
    key_phrases TEXT[] DEFAULT '{}',
    attachment_analysis JSONB DEFAULT '{}',
    llm_model VARCHAR(100),
    llm_tokens_used INT DEFAULT 0,
    processing_time_ms INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PII MAPPINGS TABLE (for re-hydration)
-- ============================================================
CREATE TABLE IF NOT EXISTS pii_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    token VARCHAR(100) NOT NULL,
    original_value TEXT NOT NULL,
    pii_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Encrypt pii original_value at rest
-- (Application-level encryption recommended; pgcrypto available for DB-level)

-- ============================================================
-- PROCESSING STATE TABLE (for SSE tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS processing_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    batch_id UUID,
    stage processing_stage NOT NULL,
    status stage_status DEFAULT 'pending',
    progress_pct DOUBLE PRECISION DEFAULT 0.0,
    message TEXT,
    error_detail TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- GEOCODING CACHE TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS geocoding_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    address_query TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    provider VARCHAR(50),
    raw_response JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(address_query)
);

-- ============================================================
-- BATCH UPLOADS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS batch_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename VARCHAR(500),
    total_rows INT DEFAULT 0,
    processed_rows INT DEFAULT 0,
    failed_rows INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending',
    error_log JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- ============================================================
-- PII-STRIPPED VIEW (safe for external use)
-- ============================================================
CREATE OR REPLACE VIEW tickets_safe AS
SELECT
    t.id,
    t.external_id,
    t.body_anonymized AS body,
    t.language,
    t.ticket_type,
    t.status,
    t.priority,
    t.priority_score,
    t.is_spam,
    t.spam_probability,
    t.text_length,
    t.text_length_times_age,
    t.id_count_of_user,
    t.assigned_manager_id,
    t.created_at,
    a.detected_type,
    a.detected_language,
    a.summary_anonymized AS summary,
    a.sentiment_score,
    a.sentiment_label
FROM tickets t
LEFT JOIN ai_analysis a ON a.ticket_id = t.id;

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_is_spam ON tickets(is_spam);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
CREATE INDEX IF NOT EXISTS idx_tickets_assigned_manager ON tickets(assigned_manager_id);
CREATE INDEX IF NOT EXISTS idx_tickets_user_email ON tickets(user_email);
CREATE INDEX IF NOT EXISTS idx_tickets_geo ON tickets USING GIST(geo_point);
CREATE INDEX IF NOT EXISTS idx_managers_geo ON managers USING GIST(geo_point);
CREATE INDEX IF NOT EXISTS idx_processing_state_ticket ON processing_state(ticket_id);
CREATE INDEX IF NOT EXISTS idx_processing_state_batch ON processing_state(batch_id);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_ticket ON ai_analysis(ticket_id);
CREATE INDEX IF NOT EXISTS idx_pii_mappings_ticket ON pii_mappings(ticket_id);
