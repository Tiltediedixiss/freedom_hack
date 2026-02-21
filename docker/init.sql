-- F.I.R.E. Database Initialization
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUM TYPES (Russian values per spec)
-- ============================================================
CREATE TYPE ticket_type AS ENUM (
    'жалоба', 'смена_данных', 'консультация', 'претензия',
    'неработоспособность', 'мошенничество', 'спам'
);

CREATE TYPE sentiment_type AS ENUM (
    'позитивный', 'нейтральный', 'негативный'
);

CREATE TYPE segment_type AS ENUM (
    'VIP', 'Priority', 'Mass'
);

CREATE TYPE manager_position AS ENUM (
    'специалист', 'ведущий_специалист', 'главный_специалист'
);

CREATE TYPE ticket_status AS ENUM (
    'new', 'ingested', 'pii_stripped', 'spam_checked',
    'analyzing', 'enriched', 'routed', 'closed'
);

CREATE TYPE processing_stage AS ENUM (
    'ingestion', 'pii_anonymization', 'spam_filter',
    'llm_analysis', 'sentiment_analysis', 'geocoding',
    'feature_engineering', 'priority_calculation', 'routing'
);

CREATE TYPE stage_status AS ENUM (
    'pending', 'in_progress', 'completed', 'failed', 'skipped'
);

CREATE TYPE address_status AS ENUM (
    'resolved', 'unknown', 'foreign', 'partial'
);

-- ============================================================
-- BUSINESS UNITS TABLE (offices)
-- ============================================================
CREATE TABLE IF NOT EXISTS business_units (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    address TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geo_point GEOGRAPHY(POINT, 4326),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- MANAGERS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS managers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name VARCHAR(255) NOT NULL,
    position manager_position NOT NULL DEFAULT 'специалист',
    skill_factor DOUBLE PRECISION DEFAULT 1.0,
    skills TEXT[] DEFAULT '{}',
    business_unit_id UUID REFERENCES business_units(id),
    csv_load INT DEFAULT 0,
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
    csv_row_index INT,
    guid VARCHAR(255),
    gender VARCHAR(20),
    birth_date DATE,
    age INT,
    description TEXT,
    description_anonymized TEXT,
    attachments TEXT[] DEFAULT '{}',
    segment segment_type,
    country VARCHAR(255),
    region VARCHAR(255),
    city VARCHAR(255),
    street VARCHAR(255),
    house VARCHAR(100),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    geo_point GEOGRAPHY(POINT, 4326),
    address_status address_status DEFAULT 'unknown',
    ticket_type ticket_type,
    status ticket_status DEFAULT 'new',
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
    language_label VARCHAR(10),
    language_actual VARCHAR(50),
    language_is_mixed BOOLEAN DEFAULT FALSE,
    language_note TEXT,
    summary TEXT,
    summary_anonymized TEXT,
    attachment_analysis TEXT,
    sentiment sentiment_type,
    sentiment_confidence DOUBLE PRECISION,
    priority_base DOUBLE PRECISION,
    priority_extra DOUBLE PRECISION,
    priority_final DOUBLE PRECISION,
    priority_breakdown JSONB DEFAULT '{}',
    anomaly_flags JSONB DEFAULT '[]',
    needs_data_change BOOLEAN DEFAULT FALSE,
    needs_location_routing BOOLEAN DEFAULT FALSE,
    llm_model VARCHAR(100),
    llm_tokens_used INT DEFAULT 0,
    processing_time_ms INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PII MAPPINGS TABLE (encrypted)
-- ============================================================
CREATE TABLE IF NOT EXISTS pii_mappings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    token VARCHAR(100) NOT NULL,
    original_value BYTEA NOT NULL,
    pii_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ASSIGNMENTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    manager_id UUID NOT NULL REFERENCES managers(id),
    business_unit_id UUID REFERENCES business_units(id),
    explanation TEXT,
    routing_details JSONB DEFAULT '{}',
    assigned_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PROCESSING STATE TABLE (SSE tracking)
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
    address_query TEXT NOT NULL UNIQUE,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    provider VARCHAR(50),
    raw_response JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
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
-- AUDIT LOG TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255),
    ticket_id UUID REFERENCES tickets(id),
    action VARCHAR(100) NOT NULL,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PII-STRIPPED VIEWS (for MCP server / star task)
-- ============================================================
CREATE OR REPLACE VIEW v_ticket_analytics AS
SELECT
    t.id AS ticket_id,
    t.csv_row_index,
    t.segment,
    t.country,
    t.city,
    t.status,
    t.is_spam,
    t.text_length,
    t.id_count_of_user,
    a.detected_type,
    a.language_label,
    a.sentiment,
    a.sentiment_confidence,
    a.priority_final,
    a.priority_breakdown,
    a.anomaly_flags,
    a.summary_anonymized AS summary,
    t.created_at
FROM tickets t
LEFT JOIN ai_analysis a ON a.ticket_id = t.id;

CREATE OR REPLACE VIEW v_assignment_overview AS
SELECT
    asgn.id AS assignment_id,
    asgn.ticket_id,
    t.csv_row_index,
    m.full_name AS manager_name,
    bu.name AS office_name,
    asgn.explanation,
    asgn.routing_details,
    asgn.assigned_at
FROM assignments asgn
JOIN tickets t ON t.id = asgn.ticket_id
JOIN managers m ON m.id = asgn.manager_id
LEFT JOIN business_units bu ON bu.id = asgn.business_unit_id;

CREATE OR REPLACE VIEW v_manager_load AS
SELECT
    m.id AS manager_id,
    m.full_name,
    m.position,
    bu.name AS office,
    m.csv_load,
    m.stress_score,
    m.skills,
    (SELECT COUNT(*) FROM assignments a WHERE a.manager_id = m.id) AS assigned_count
FROM managers m
LEFT JOIN business_units bu ON bu.id = m.business_unit_id;

CREATE OR REPLACE VIEW v_priority_distribution AS
SELECT
    a.priority_final,
    a.detected_type,
    a.sentiment,
    t.segment,
    COUNT(*) AS ticket_count
FROM ai_analysis a
JOIN tickets t ON t.id = a.ticket_id
WHERE t.is_spam = FALSE
GROUP BY a.priority_final, a.detected_type, a.sentiment, t.segment;

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_is_spam ON tickets(is_spam);
CREATE INDEX IF NOT EXISTS idx_tickets_guid ON tickets(guid);
CREATE INDEX IF NOT EXISTS idx_tickets_csv_row ON tickets(csv_row_index);
CREATE INDEX IF NOT EXISTS idx_tickets_assigned_manager ON tickets(assigned_manager_id);
CREATE INDEX IF NOT EXISTS idx_tickets_geo ON tickets USING GIST(geo_point);
CREATE INDEX IF NOT EXISTS idx_managers_geo ON business_units USING GIST(geo_point);
CREATE INDEX IF NOT EXISTS idx_processing_state_ticket ON processing_state(ticket_id);
CREATE INDEX IF NOT EXISTS idx_processing_state_batch ON processing_state(batch_id);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_ticket ON ai_analysis(ticket_id);
CREATE INDEX IF NOT EXISTS idx_pii_mappings_ticket ON pii_mappings(ticket_id);
CREATE INDEX IF NOT EXISTS idx_assignments_ticket ON assignments(ticket_id);
CREATE INDEX IF NOT EXISTS idx_assignments_manager ON assignments(manager_id);

-- ============================================================
-- RESTRICTED ROLE for MCP Server
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fire_readonly') THEN
        CREATE ROLE fire_readonly LOGIN PASSWORD 'readonly_secret';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE fire_db TO fire_readonly;
GRANT USAGE ON SCHEMA public TO fire_readonly;
GRANT SELECT ON v_ticket_analytics, v_assignment_overview, v_manager_load, v_priority_distribution TO fire_readonly;
