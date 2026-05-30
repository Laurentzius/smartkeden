-- Classification Rules Engine: Database Schema
-- Migration 001: Create classification_rules and rules_audit_log tables

CREATE TABLE IF NOT EXISTS classification_rules (
    rule_id VARCHAR(100) PRIMARY KEY,
    category_mask VARCHAR(20) NOT NULL,  -- "9503*" or "*" for all
    priority INT DEFAULT 0,  -- higher = checked first
    conditions JSONB NOT NULL,
    action JSONB NOT NULL,
    source TEXT NOT NULL,  -- official document reference (required)
    effective_date DATE NOT NULL,
    expiry_date DATE,
    created_by VARCHAR(100),
    version INT DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rules_category ON classification_rules(category_mask);
CREATE INDEX IF NOT EXISTS idx_rules_active ON classification_rules(is_active);
CREATE INDEX IF NOT EXISTS idx_rules_priority ON classification_rules(priority DESC);

CREATE TABLE IF NOT EXISTS rules_audit_log (
    id SERIAL PRIMARY KEY,
    rule_id VARCHAR(100),
    action VARCHAR(50),  -- "applied", "created", "updated", "deleted"
    product_description TEXT,
    attributes JSONB,
    old_candidates JSONB,
    new_candidates JSONB,
    timestamp TIMESTAMP DEFAULT NOW(),
    session_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_audit_rule ON rules_audit_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON rules_audit_log(timestamp DESC);
