-- ============================================================
-- CloudCostMonitor — Database Schema
-- Run this once against your Postgres database.
-- Compatible with plain Postgres 14+ and TimescaleDB.
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ============================================================
-- TABLE: tenants
-- One row per company using your platform.
-- ============================================================
CREATE TABLE IF NOT EXISTS tenants (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL,                      -- "Acme Corp"
    email           TEXT        NOT NULL UNIQUE,               -- billing/admin email
    plan            TEXT        NOT NULL DEFAULT 'free',       -- free | starter | pro | enterprise
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ============================================================
-- TABLE: users
-- People who log into the dashboard.
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           TEXT        NOT NULL UNIQUE,
    name            TEXT        NOT NULL DEFAULT '',
    role            TEXT        NOT NULL DEFAULT 'member',     -- owner | admin | member | viewer
    password_hash   TEXT        NOT NULL,                      -- bcrypt hash — never plain text
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);


-- ============================================================
-- TABLE: aws_accounts
-- One row per AWS account a customer connects.
-- Stores the IAM role ARN — never stores actual credentials.
-- ============================================================
CREATE TABLE IF NOT EXISTS aws_accounts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- AWS identity
    aws_account_id  TEXT        NOT NULL,                      -- 12-digit AWS account ID
    account_alias   TEXT        NOT NULL DEFAULT '',           -- human name, e.g. "prod-account"
    display_name    TEXT        NOT NULL DEFAULT '',           -- customer-chosen label

    -- Secure cross-account access (never store secret keys here)
    role_arn        TEXT        NOT NULL,                      -- arn:aws:iam::123456789012:role/CloudCostMonitor-ReadOnly
    external_id     TEXT        NOT NULL,                      -- the UUID used in the trust policy
    -- In production: encrypt role_arn and external_id at the app layer using your KMS key

    -- Sync state
    status          TEXT        NOT NULL DEFAULT 'pending',    -- pending | active | error | disconnected
    last_synced_at  TIMESTAMPTZ,
    last_error      TEXT,
    sync_enabled    BOOLEAN     NOT NULL DEFAULT true,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(tenant_id, aws_account_id)
);

CREATE INDEX IF NOT EXISTS idx_aws_accounts_tenant ON aws_accounts(tenant_id);


-- ============================================================
-- TABLE: cost_records
-- Core time-series table. One row per service per day per account.
-- This is your highest-volume table — index carefully.
-- ============================================================
CREATE TABLE IF NOT EXISTS cost_records (
    id                  TEXT        PRIMARY KEY,               -- deterministic SHA hash (safe to upsert)
    tenant_id           UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id      TEXT        NOT NULL,
    account_alias       TEXT        NOT NULL DEFAULT '',

    -- Time
    date                DATE        NOT NULL,
    granularity         TEXT        NOT NULL DEFAULT 'DAILY',  -- DAILY | MONTHLY | HOURLY

    -- What was used
    provider            TEXT        NOT NULL DEFAULT 'aws',
    service             TEXT        NOT NULL,                  -- "Amazon EC2"
    service_group       TEXT        NOT NULL DEFAULT 'other',  -- compute | storage | database | network | ai_ml | analytics | management | other
    region              TEXT        NOT NULL DEFAULT 'global', -- "us-east-1" or "global"

    -- Cost
    cost_usd            NUMERIC(14,6) NOT NULL DEFAULT 0,
    usage_quantity      NUMERIC(16,4) NOT NULL DEFAULT 0,
    usage_unit          TEXT        NOT NULL DEFAULT '',       -- "Hrs", "GB-Mo", etc.

    -- Tags (from AWS resource tags — maps team, env, project etc.)
    tags                JSONB       NOT NULL DEFAULT '{}',

    -- Metadata
    ingested_at         TIMESTAMPTZ NOT NULL,
    raw_service_name    TEXT        NOT NULL DEFAULT '',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Primary query patterns
CREATE INDEX IF NOT EXISTS idx_cost_records_account_date
    ON cost_records (aws_account_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_cost_records_tenant_date
    ON cost_records (tenant_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_cost_records_service_group
    ON cost_records (aws_account_id, service_group, date DESC);

CREATE INDEX IF NOT EXISTS idx_cost_records_region
    ON cost_records (aws_account_id, region, date DESC);

CREATE INDEX IF NOT EXISTS idx_cost_records_tags
    ON cost_records USING GIN (tags);

-- TimescaleDB (optional — run if timescaledb extension is installed):
-- SELECT create_hypertable('cost_records', 'date', if_not_exists => TRUE);


-- ============================================================
-- TABLE: resource_inventory
-- Snapshot of all running resources (updated on each sync).
-- Used for waste detection and rightsizing.
-- ============================================================
CREATE TABLE IF NOT EXISTS resource_inventory (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id  TEXT        NOT NULL,

    resource_id     TEXT        NOT NULL,                      -- "i-0abc123def456"
    resource_type   TEXT        NOT NULL,                      -- "ec2_instance" | "rds_instance" | "s3_bucket" | "ebs_volume" etc.
    service_group   TEXT        NOT NULL DEFAULT 'other',
    region          TEXT        NOT NULL,
    name            TEXT        NOT NULL DEFAULT '',           -- from Name tag
    state           TEXT        NOT NULL DEFAULT 'unknown',    -- running | stopped | available | idle

    -- Cost & utilisation
    monthly_cost_usd    NUMERIC(10,2),
    cpu_avg_pct         NUMERIC(5,2),                         -- average CPU over last 14 days
    memory_avg_pct      NUMERIC(5,2),
    is_idle             BOOLEAN NOT NULL DEFAULT false,        -- true if CPU < 5% for 14+ days

    -- Metadata
    tags            JSONB       NOT NULL DEFAULT '{}',
    raw_data        JSONB       NOT NULL DEFAULT '{}',         -- full AWS describe response
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(aws_account_id, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_resources_tenant ON resource_inventory(tenant_id);
CREATE INDEX IF NOT EXISTS idx_resources_idle   ON resource_inventory(aws_account_id, is_idle) WHERE is_idle = true;
CREATE INDEX IF NOT EXISTS idx_resources_type   ON resource_inventory(aws_account_id, resource_type);


-- ============================================================
-- TABLE: budgets
-- Customer-defined spending limits. Your platform checks these on every sync.
-- ============================================================
CREATE TABLE IF NOT EXISTS budgets (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id  TEXT,                                      -- NULL means "applies to all accounts"

    name            TEXT        NOT NULL,                      -- "Monthly EC2 budget"
    service_group   TEXT,                                      -- NULL means total spend
    region          TEXT,                                      -- NULL means all regions

    limit_usd       NUMERIC(12,2) NOT NULL,
    period          TEXT        NOT NULL DEFAULT 'monthly',    -- monthly | weekly | daily
    alert_at_pct    INTEGER     NOT NULL DEFAULT 80,           -- alert when spend reaches this %

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_budgets_tenant ON budgets(tenant_id);


-- ============================================================
-- TABLE: alert_events
-- Log of every alert that fired. Never delete — audit trail.
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    budget_id       UUID        REFERENCES budgets(id),
    aws_account_id  TEXT,

    alert_type      TEXT        NOT NULL,                      -- budget_threshold | spend_spike | idle_resource | forecast_breach
    severity        TEXT        NOT NULL DEFAULT 'warning',    -- info | warning | critical
    title           TEXT        NOT NULL,
    message         TEXT        NOT NULL,

    -- Values at time of alert
    current_value   NUMERIC(14,2),
    threshold_value NUMERIC(14,2),
    percent_used    NUMERIC(5,1),

    -- Delivery
    channels        JSONB       NOT NULL DEFAULT '[]',         -- ["slack", "email"]
    delivered_at    TIMESTAMPTZ,
    delivery_error  TEXT,

    -- State machine — prevents re-alerting on same breach
    state           TEXT        NOT NULL DEFAULT 'firing',     -- firing | resolved | acknowledged
    resolved_at     TIMESTAMPTZ,

    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_alerts_tenant      ON alert_events(tenant_id, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_state       ON alert_events(tenant_id, state) WHERE state = 'firing';
CREATE INDEX IF NOT EXISTS idx_alerts_account     ON alert_events(aws_account_id, triggered_at DESC);


-- ============================================================
-- TABLE: ingestion_jobs
-- Audit log of every data pull. Helps diagnose sync issues.
-- ============================================================
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id  TEXT        NOT NULL,

    status          TEXT        NOT NULL DEFAULT 'running',    -- running | success | error
    records_pulled  INTEGER     NOT NULL DEFAULT 0,
    error_message   TEXT,

    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_tenant  ON ingestion_jobs(tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_account ON ingestion_jobs(aws_account_id, started_at DESC);


-- ============================================================
-- USEFUL VIEWS
-- Pre-built queries your API will use constantly
-- ============================================================

-- Monthly spend totals per account per service group
CREATE OR REPLACE VIEW v_monthly_spend AS
SELECT
    tenant_id,
    aws_account_id,
    account_alias,
    DATE_TRUNC('month', date) AS month,
    service_group,
    SUM(cost_usd)             AS total_usd,
    COUNT(DISTINCT service)   AS service_count
FROM cost_records
WHERE granularity = 'DAILY'
GROUP BY tenant_id, aws_account_id, account_alias, DATE_TRUNC('month', date), service_group;


-- Daily spend totals — for trend charts
CREATE OR REPLACE VIEW v_daily_spend AS
SELECT
    tenant_id,
    aws_account_id,
    account_alias,
    date,
    SUM(cost_usd)       AS total_usd,
    COUNT(DISTINCT service) AS active_services
FROM cost_records
WHERE granularity = 'DAILY'
GROUP BY tenant_id, aws_account_id, account_alias, date;


-- Top 20 most expensive services this month
CREATE OR REPLACE VIEW v_top_services_this_month AS
SELECT
    tenant_id,
    aws_account_id,
    service,
    service_group,
    SUM(cost_usd) AS total_usd
FROM cost_records
WHERE
    granularity = 'DAILY'
    AND date >= DATE_TRUNC('month', CURRENT_DATE)
GROUP BY tenant_id, aws_account_id, service, service_group
ORDER BY total_usd DESC;


-- ============================================================
-- AI AGENT TABLES
-- ============================================================

-- ============================================================
-- TABLE: ai_recommendations
-- Store optimization recommendations generated by AI agents
-- ============================================================
CREATE TABLE IF NOT EXISTS ai_recommendations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id  TEXT,                                      -- NULL means applies to all accounts
    
    agent_type      TEXT        NOT NULL,                      -- optimizer | anomaly | forecaster | reporter | analyzer
    recommendation_type TEXT     NOT NULL,                      -- stop_idle_resource | rightsizing | unused_service | etc
    title           TEXT        NOT NULL,
    description     TEXT        NOT NULL,
    
    priority        TEXT        NOT NULL DEFAULT 'medium',     -- low | medium | high | critical
    estimated_savings_usd NUMERIC(12,2),
    confidence_score NUMERIC(3,2),                             -- 0.0 to 1.0
    
    action_steps    JSONB       NOT NULL DEFAULT '[]',         -- array of {step, details}
    
    status          TEXT        NOT NULL DEFAULT 'pending',    -- pending | accepted | rejected | implemented | archived
    feedback        JSONB,                                     -- {rating, notes, implemented_at}
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ                                -- when recommendation is no longer relevant
);

CREATE INDEX IF NOT EXISTS idx_recommendations_tenant 
    ON ai_recommendations(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recommendations_status 
    ON ai_recommendations(tenant_id, status) WHERE status != 'archived';
CREATE INDEX IF NOT EXISTS idx_recommendations_type 
    ON ai_recommendations(tenant_id, recommendation_type);


-- ============================================================
-- TABLE: anomaly_events
-- Detected unusual cost patterns
-- ============================================================
CREATE TABLE IF NOT EXISTS anomaly_events (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id  TEXT        NOT NULL,
    
    anomaly_type    TEXT        NOT NULL,                      -- spend_spike | new_service | unusual_pattern | regional_shift
    severity        TEXT        NOT NULL DEFAULT 'warning',    -- info | warning | critical
    
    service         TEXT,
    region          TEXT,
    
    current_value   NUMERIC(14,2) NOT NULL,
    baseline_value  NUMERIC(14,2),
    percent_change  NUMERIC(7,2),                              -- e.g., 275.50
    
    description     TEXT        NOT NULL,
    suspected_cause TEXT,
    
    state           TEXT        NOT NULL DEFAULT 'firing',     -- firing | resolved | acknowledged
    resolved_at     TIMESTAMPTZ,
    
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_tenant 
    ON anomaly_events(tenant_id, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_state 
    ON anomaly_events(tenant_id, state) WHERE state = 'firing';
CREATE INDEX IF NOT EXISTS idx_anomalies_account 
    ON anomaly_events(aws_account_id, triggered_at DESC);


-- ============================================================
-- TABLE: forecast_records
-- Spending forecasts and projections
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_records (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    aws_account_id  TEXT,                                      -- NULL means platform-wide
    
    forecast_period TEXT        NOT NULL DEFAULT 'monthly',    -- daily | weekly | monthly
    forecast_date   DATE        NOT NULL,                      -- the date this forecast is for
    
    forecasted_cost_usd NUMERIC(14,2) NOT NULL,
    confidence_level NUMERIC(3,2),                             -- 0.0 to 1.0
    
    method          TEXT        NOT NULL,                      -- linear | exponential | ml | seasonal
    
    budget_limit    NUMERIC(12,2),
    budget_breach_probability NUMERIC(3,2),                    -- probability of exceeding budget
    days_to_breach  INTEGER,                                   -- null if no breach expected
    
    notes           TEXT,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_forecasts_tenant 
    ON forecast_records(tenant_id, forecast_date DESC);
CREATE INDEX IF NOT EXISTS idx_forecasts_account 
    ON forecast_records(aws_account_id, forecast_date DESC);


-- ============================================================
-- TABLE: agent_runs
-- Audit log of all agent executions
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    
    agent_type      TEXT        NOT NULL,                      -- optimizer | anomaly | nlq | forecaster | reporter | analyzer
    trigger_type    TEXT        NOT NULL,                      -- scheduled | manual | webhook | event
    
    status          TEXT        NOT NULL DEFAULT 'pending',    -- pending | running | success | error | timeout
    
    input_data      JSONB       NOT NULL DEFAULT '{}',
    output_data     JSONB       NOT NULL DEFAULT '{}',
    
    error_message   TEXT,
    
    api_model       TEXT,                                      -- e.g., "claude-3-5-sonnet-20241022"
    tokens_used     INTEGER,
    cost_usd        NUMERIC(10,6),
    
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant 
    ON agent_runs(tenant_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_type 
    ON agent_runs(agent_type, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status 
    ON agent_runs(status) WHERE status IN ('pending', 'running');


-- ============================================================
-- TABLE: query_cache
-- Cache results of expensive queries to minimize API calls
-- ============================================================
CREATE TABLE IF NOT EXISTS query_cache (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    
    cache_key       TEXT        NOT NULL,                      -- hash of query/params
    result_data     JSONB       NOT NULL,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    
    UNIQUE(cache_key)
);

CREATE INDEX IF NOT EXISTS idx_cache_tenant 
    ON query_cache(tenant_id, expires_at DESC);
