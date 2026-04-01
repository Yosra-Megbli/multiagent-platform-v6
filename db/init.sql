-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Tenants ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   VARCHAR(100) PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    sector      VARCHAR(50)  NOT NULL,  -- "supply_chain" | "legal" | "hr" | "real_estate"
    plan        VARCHAR(20)  DEFAULT 'starter',
    api_key     VARCHAR(200) UNIQUE NOT NULL,
    config      JSONB        DEFAULT '{}',
    active      BOOLEAN      DEFAULT TRUE,
    created_at  TIMESTAMP    DEFAULT NOW()
);

-- ─── Supply Chain Tables ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sales (
    id          SERIAL PRIMARY KEY,
    tenant_id   VARCHAR(100) REFERENCES tenants(tenant_id),
    product_id  VARCHAR(100) NOT NULL,
    sale_date   DATE         NOT NULL,
    quantity    FLOAT        NOT NULL,
    created_at  TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX idx_sales_tenant_product ON sales(tenant_id, product_id, sale_date);

CREATE TABLE IF NOT EXISTS production_config (
    tenant_id            VARCHAR(100) REFERENCES tenants(tenant_id),
    product_id           VARCHAR(100) NOT NULL,
    daily_capacity       INTEGER NOT NULL,
    current_stock        INTEGER NOT NULL,
    packaging_stock      INTEGER NOT NULL,
    supplier_lead_time   INTEGER DEFAULT 4,
    updated_at           TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (tenant_id, product_id)
);

-- ─── Decisions (all sectors) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS decisions (
    id            SERIAL PRIMARY KEY,
    tenant_id     VARCHAR(100) REFERENCES tenants(tenant_id),
    sector        VARCHAR(50)  NOT NULL,
    decision_text TEXT         NOT NULL,
    insights      TEXT,
    created_at    TIMESTAMP    DEFAULT NOW()
);

-- ─── Sample Data ─────────────────────────────────────────────────────────────
INSERT INTO tenants (tenant_id, name, sector, plan, api_key)
VALUES ('client_demo', 'Demo Company', 'supply_chain', 'pro', 'sk-demo-123456')
ON CONFLICT DO NOTHING;

INSERT INTO production_config (tenant_id, product_id, daily_capacity, current_stock, packaging_stock, supplier_lead_time)
VALUES ('client_demo', 'ICE_CREAM_VANILLA', 10000, 25000, 18000, 4)
ON CONFLICT DO NOTHING;

-- 365 days of sample sales
INSERT INTO sales (tenant_id, product_id, sale_date, quantity)
SELECT
    'client_demo',
    'ICE_CREAM_VANILLA',
    CURRENT_DATE - (s || ' days')::interval,
    800 + (RANDOM() * 400)::int +
    CASE
        WHEN EXTRACT(MONTH FROM CURRENT_DATE - (s || ' days')::interval) IN (6,7,8)
        THEN 2000 ELSE 0
    END
FROM generate_series(1, 365) s
ON CONFLICT DO NOTHING;

-- ─── Decision Memory (RAG) ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS decision_memory (
    id            SERIAL PRIMARY KEY,
    tenant_id     VARCHAR(100) REFERENCES tenants(tenant_id),
    product_id    VARCHAR(100) NOT NULL,
    sector        VARCHAR(50)  NOT NULL,
    summary       TEXT         NOT NULL,
    decision_text TEXT         NOT NULL,
    insights      JSONB,
    accuracy      FLOAT,
    embedding     vector(384),
    created_at    TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_decision_memory_tenant
    ON decision_memory(tenant_id, sector);
CREATE INDEX IF NOT EXISTS idx_decision_memory_vector
    ON decision_memory USING ivfflat (embedding vector_cosine_ops);

-- ─── Tenants: add role column ────────────────────────────────────────────────
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'analyst';
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS user_id VARCHAR(100);

-- Update demo tenant
UPDATE tenants SET role = 'admin', user_id = 'demo-user-001'
WHERE tenant_id = 'client_demo';

-- ─── ERP Connector Config Examples ──────────────────────────────────────────
-- To connect a tenant to an external ERP via REST API, update their config:
--
-- UPDATE tenants
-- SET config = '{
--   "connector_type": "rest_api",
--   "base_url": "https://erp.client.tn",
--   "sales_endpoint": "/api/sales",
--   "production_endpoint": "/api/stock",
--   "headers": {"Authorization": "Bearer TOKEN"}
-- }'
-- WHERE tenant_id = 'client_coca';
--
-- For Google Sheets:
-- UPDATE tenants
-- SET config = '{
--   "connector_type": "google_sheets",
--   "spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
--   "credentials_secret": "google_sheets_creds"
-- }'
-- WHERE tenant_id = 'client_X';
--
-- For CSV (dev/testing):
-- UPDATE tenants
-- SET config = '{"connector_type": "csv", "file_path": "/data/sales.csv"}'
-- WHERE tenant_id = 'client_Y';

-- ─── Demo tenant for frontend (demo-key-001) ─────────────────────────────────
INSERT INTO tenants (tenant_id, name, sector, plan, api_key, role, user_id)
VALUES ('demo', 'My Company', 'supply_chain', 'enterprise', 'demo-key-001', 'admin', 'demo-user-001')
ON CONFLICT DO NOTHING;

INSERT INTO tenants (tenant_id, name, sector, plan, api_key, role, user_id)
VALUES ('test', 'Test Company', 'supply_chain', 'starter', 'test-key-002', 'analyst', 'test-user-002')
ON CONFLICT DO NOTHING;

-- Production config for ERP products
INSERT INTO production_config (tenant_id, product_id, daily_capacity, current_stock, packaging_stock, supplier_lead_time)
VALUES
  ('demo', 'HARISSA-140G',  150, 3000, 5000, 5),
  ('demo', 'SARDINE-125G',  120, 2500, 4000, 5),
  ('demo', 'THON-160G',     100, 1800, 3000, 7),
  ('demo', 'HUILE-500ML',    80, 1200, 2500, 7),
  ('demo', 'SKU-ALPHA',     150, 3000, 5000, 5)
ON CONFLICT DO NOTHING;
