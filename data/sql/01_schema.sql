-- ============================================================
-- TrustFlow Banking Agent - Database Schema (PostgreSQL)
-- Generated from CSV data
-- ============================================================

-- Drop indexes (safe cleanup)
DROP INDEX IF EXISTS idx_ext_bank_acc_unique;
DROP INDEX IF EXISTS idx_accounts_cif;
DROP INDEX IF EXISTS idx_cards_cif;
DROP INDEX IF EXISTS idx_beneficiaries_cif;
DROP INDEX IF EXISTS idx_transactions_cif;
DROP INDEX IF EXISTS idx_transactions_time;
DROP INDEX IF EXISTS idx_transactions_type;
DROP INDEX IF EXISTS idx_transactions_cif_time;
DROP INDEX IF EXISTS idx_transactions_cif_type;
DROP INDEX IF EXISTS idx_action_requests_cif;
DROP INDEX IF EXISTS idx_audit_logs_action;
DROP INDEX IF EXISTS idx_cba_cif;
DROP INDEX IF EXISTS idx_fraud_reports_reporter;
DROP INDEX IF EXISTS idx_fraud_reports_account;
DROP INDEX IF EXISTS idx_reported_accounts_lookup;
DROP INDEX IF EXISTS idx_reported_customers_cif;
DROP INDEX IF EXISTS idx_fraud_decisions_action;
DROP INDEX IF EXISTS idx_bills_lookup;
DROP INDEX IF EXISTS idx_interest_rates_lookup;
DROP INDEX IF EXISTS idx_chat_sessions_user_updated_at;
DROP INDEX IF EXISTS idx_chat_messages_session_created_at;
DROP INDEX IF EXISTS idx_agent_memory_lookup;
DROP INDEX IF EXISTS idx_agent_memory_expires;
DROP INDEX IF EXISTS idx_conversation_tasks_session_lifecycle;
DROP INDEX IF EXISTS idx_conversation_tasks_user_updated;

-- Drop tables in reverse dependency order
DROP TABLE IF EXISTS conversation_tasks CASCADE;
DROP TABLE IF EXISTS chat_messages CASCADE;
DROP TABLE IF EXISTS card_operation_requests CASCADE;
DROP TABLE IF EXISTS card_limits CASCADE;
DROP TABLE IF EXISTS card_controls CASCADE;
DROP TABLE IF EXISTS account_products CASCADE;
DROP TABLE IF EXISTS agent_memory CASCADE;
DROP TABLE IF EXISTS fraud_decisions CASCADE;
DROP TABLE IF EXISTS reported_customers CASCADE;
DROP TABLE IF EXISTS reported_accounts CASCADE;
DROP TABLE IF EXISTS fraud_reports CASCADE;
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS api_call_logs CASCADE;
DROP TABLE IF EXISTS action_requests CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS transaction_categories CASCADE;
DROP TABLE IF EXISTS bills CASCADE;
DROP TABLE IF EXISTS interest_rates CASCADE;
DROP TABLE IF EXISTS customer_biller_accounts CASCADE;
DROP TABLE IF EXISTS billers CASCADE;
DROP TABLE IF EXISTS merchants CASCADE;
DROP TABLE IF EXISTS beneficiaries CASCADE;
DROP TABLE IF EXISTS cards CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS external_bank_accounts CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS chat_sessions CASCADE;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE customers (
    customer_id UUID PRIMARY KEY,
    cif_no VARCHAR(20) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    phone_number VARCHAR(15),
    email VARCHAR(100),
    kyc_level VARCHAR(10) CHECK(kyc_level IN ('BASIC','VERIFIED','ENHANCED')),
    status VARCHAR(10) CHECK(status IN ('ACTIVE','SUSPENDED','CLOSED')),
    created_at TIMESTAMP
);

CREATE TABLE accounts (
    account_id UUID PRIMARY KEY,
    account_no VARCHAR(20) UNIQUE NOT NULL,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    account_type VARCHAR(30) CHECK(account_type IN ('PAYMENT','SAVINGS','CREDIT_CARD_SETTLEMENT')),
    currency VARCHAR(5) DEFAULT 'VND',
    balance BIGINT,
    available_balance BIGINT,
    status VARCHAR(10) CHECK(status IN ('ACTIVE','FROZEN','CLOSED')),
    is_primary BOOLEAN DEFAULT FALSE,
    closed_at TIMESTAMP,
    nickname VARCHAR(100),
    opened_at TIMESTAMP
);

CREATE TABLE cards (
    card_id UUID PRIMARY KEY,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    account_no VARCHAR(20) NOT NULL REFERENCES accounts(account_no),
    masked_card_no VARCHAR(25),
    card_type VARCHAR(10) CHECK(card_type IN ('DEBIT','CREDIT')),
    card_network VARCHAR(15) CHECK(card_network IN ('VISA','MASTERCARD','NAPAS')),
    credit_limit BIGINT,
    available_limit BIGINT,
    status VARCHAR(20) CHECK(status IN ('ACTIVE','TEMP_LOCKED','LOST','STOLEN','BLOCKED_BY_BANK','EXPIRED','CLOSED')),
    issued_at TIMESTAMP
);

CREATE TABLE beneficiaries (
    beneficiary_id UUID PRIMARY KEY,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    beneficiary_name VARCHAR(100) NOT NULL,
    beneficiary_account_no VARCHAR(20),
    beneficiary_bank_code VARCHAR(10),
    beneficiary_bank_name VARCHAR(50),
    nickname VARCHAR(50),
    is_saved BOOLEAN,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP
);

CREATE TABLE merchants (
    merchant_id UUID PRIMARY KEY,
    merchant_name VARCHAR(100) NOT NULL,
    merchant_category VARCHAR(20),
    mcc_code VARCHAR(10),
    city VARCHAR(30),
    country VARCHAR(5) DEFAULT 'VN',
    status VARCHAR(10) CHECK(status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE billers (
    biller_id UUID PRIMARY KEY,
    biller_code VARCHAR(30) UNIQUE NOT NULL,
    biller_name VARCHAR(100) NOT NULL,
    biller_type VARCHAR(20) CHECK(biller_type IN ('ELECTRICITY','WATER','INTERNET','PHONE_POSTPAID')),
    provider VARCHAR(20),
    status VARCHAR(10) CHECK(status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE customer_biller_accounts (
    customer_biller_account_id UUID PRIMARY KEY,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    biller_id UUID NOT NULL REFERENCES billers(biller_id),
    customer_bill_code VARCHAR(30),
    alias VARCHAR(50),
    status VARCHAR(10) CHECK(status IN ('ACTIVE','INACTIVE')),
    last_paid_at TIMESTAMP
);

CREATE TABLE bills (
    bill_id UUID PRIMARY KEY,
    biller_code VARCHAR(30) NOT NULL REFERENCES billers(biller_code),
    customer_bill_code VARCHAR(30) NOT NULL,
    bill_period VARCHAR(20) NOT NULL,
    amount_due NUMERIC(18,2) NOT NULL,
    due_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'UNPAID' CHECK(status IN ('UNPAID','PAID','CANCELLED')),
    created_at TIMESTAMP DEFAULT NOW(),
    paid_at TIMESTAMP
);

CREATE TABLE interest_rates (
    id UUID PRIMARY KEY,
    product_code VARCHAR(50) NOT NULL,
    product_type VARCHAR(30) NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    currency VARCHAR(3) DEFAULT 'VND',
    term_months INT,
    annual_rate NUMERIC(5,2) NOT NULL,
    min_amount NUMERIC(18,0),
    max_amount NUMERIC(18,0),
    customer_segment VARCHAR(30) DEFAULT 'ALL',
    channel VARCHAR(20) DEFAULT 'ALL',
    effective_from DATE NOT NULL,
    effective_to DATE,
    status VARCHAR(10) DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(product_code)
);

CREATE TABLE transaction_categories (
    category_id UUID PRIMARY KEY,
    category_code VARCHAR(20) UNIQUE NOT NULL,
    category_name VARCHAR(50) NOT NULL,
    category_group VARCHAR(10)
);

CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY,
    transaction_ref VARCHAR(30) UNIQUE NOT NULL,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    account_no VARCHAR(20) NOT NULL REFERENCES accounts(account_no),
    card_id UUID REFERENCES cards(card_id),
    transaction_time TIMESTAMP NOT NULL,
    amount BIGINT NOT NULL,
    currency VARCHAR(5) DEFAULT 'VND',
    direction VARCHAR(3) CHECK(direction IN ('IN','OUT')),
    transaction_type VARCHAR(20),
    category_id UUID REFERENCES transaction_categories(category_id),
    merchant_id UUID REFERENCES merchants(merchant_id),
    biller_id UUID REFERENCES billers(biller_id),
    beneficiary_id UUID REFERENCES beneficiaries(beneficiary_id),
    counterparty_account_no VARCHAR(20),
    counterparty_bank_code VARCHAR(10),
    counterparty_name VARCHAR(100),
    channel VARCHAR(20),
    note TEXT,
    description TEXT,
    status VARCHAR(10) CHECK(status IN ('SUCCESS','FAILED','REVERSED','PENDING')),
    balance_after BIGINT,
    external_reference VARCHAR(30),
    created_at TIMESTAMP
);

CREATE TABLE action_requests (
    action_id UUID PRIMARY KEY,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    action_type VARCHAR(30),
    status VARCHAR(25),
    user_text TEXT,
    api_name VARCHAR(50),
    api_payload JSONB,
    resolved_entities JSONB,
    missing_fields JSONB,
    risk_score NUMERIC(4,2),
    risk_tier VARCHAR(10) CHECK(risk_tier IN ('GREEN','YELLOW','ORANGE','RED')),
    requires_confirmation BOOLEAN,
    requires_otp BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE TABLE api_call_logs (
    api_call_id UUID PRIMARY KEY,
    action_id UUID NOT NULL REFERENCES action_requests(action_id),
    api_name VARCHAR(50),
    request_payload JSONB,
    response_payload JSONB,
    http_status INTEGER,
    status VARCHAR(10) CHECK(status IN ('SUCCESS','FAILED')),
    created_at TIMESTAMP
);

CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY,
    action_id UUID REFERENCES action_requests(action_id),
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    event_type VARCHAR(30),
    actor VARCHAR(20),
    event_payload JSONB,
    created_at TIMESTAMP
);

CREATE TABLE fraud_reports (
    report_id UUID PRIMARY KEY,
    reporter_cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    transaction_ref VARCHAR(30) REFERENCES transactions(transaction_ref),
    reported_account_no VARCHAR(20) NOT NULL,
    reported_bank_code VARCHAR(10) NOT NULL,
    reported_customer_cif VARCHAR(20),
    fraud_type VARCHAR(30),
    contact_channel VARCHAR(20),
    aftermath VARCHAR(30),
    reason_text TEXT,
    has_evidence BOOLEAN DEFAULT FALSE,
    confidence_score INTEGER CHECK(confidence_score BETWEEN 0 AND 100),
    status VARCHAR(15) CHECK(status IN ('SUBMITTED','VALIDATED','CONFIRMED','REJECTED')) DEFAULT 'SUBMITTED',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE reported_accounts (
    reported_account_id UUID PRIMARY KEY,
    account_no VARCHAR(20) NOT NULL,
    bank_code VARCHAR(10) NOT NULL,
    linked_customer_cif VARCHAR(20),
    valid_report_count INTEGER DEFAULT 0,
    unique_reporter_count INTEGER DEFAULT 0,
    total_reported_amount BIGINT DEFAULT 0,
    avg_confidence_score INTEGER DEFAULT 0,
    risk_score NUMERIC(4,2) DEFAULT 0.0,
    risk_level VARCHAR(10) CHECK(risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')) DEFAULT 'LOW',
    status VARCHAR(15) CHECK(status IN ('ACTIVE','UNDER_REVIEW','CLEARED')) DEFAULT 'ACTIVE',
    first_reported_at TIMESTAMP,
    last_reported_at TIMESTAMP,
    UNIQUE(account_no, bank_code)
);

CREATE TABLE reported_customers (
    reported_customer_id UUID PRIMARY KEY,
    cif_no VARCHAR(20) NOT NULL REFERENCES customers(cif_no),
    reported_account_count INTEGER DEFAULT 0,
    valid_report_count INTEGER DEFAULT 0,
    total_reported_amount BIGINT DEFAULT 0,
    risk_score NUMERIC(4,2) DEFAULT 0.0,
    risk_level VARCHAR(10) CHECK(risk_level IN ('WATCH','FROZEN','BLOCKED','CLEARED')) DEFAULT 'WATCH',
    status VARCHAR(15) DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE fraud_decisions (
    decision_id UUID PRIMARY KEY,
    action_id UUID REFERENCES action_requests(action_id),
    receiver_account_no VARCHAR(20) NOT NULL,
    receiver_bank_code VARCHAR(10) NOT NULL,
    matched_report_count INTEGER DEFAULT 0,
    risk_score NUMERIC(4,2) DEFAULT 0.0,
    risk_level VARCHAR(10),
    decision VARCHAR(15) CHECK(decision IN ('ALLOW','WARN','STEP_UP_AUTH','HOLD','BLOCK')),
    reason_codes JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE external_bank_accounts (
    id INTEGER PRIMARY KEY,
    account_no VARCHAR(20) NOT NULL,
    account_holder_name VARCHAR(100) NOT NULL,
    bank_code VARCHAR(10) NOT NULL,
    bank_name VARCHAR(50) NOT NULL,
    id_number VARCHAR(20),
    phone VARCHAR(15),
    status VARCHAR(10) DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE card_controls (
    card_id UUID PRIMARY KEY REFERENCES cards(card_id),
    online_payment_enabled BOOLEAN DEFAULT TRUE,
    international_payment_enabled BOOLEAN DEFAULT FALSE,
    atm_withdrawal_enabled BOOLEAN DEFAULT TRUE,
    pos_payment_enabled BOOLEAN DEFAULT TRUE,
    contactless_enabled BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE card_limits (
    card_id UUID PRIMARY KEY REFERENCES cards(card_id),
    daily_atm_limit BIGINT DEFAULT 50000000,
    daily_pos_limit BIGINT DEFAULT 100000000,
    daily_online_limit BIGINT DEFAULT 30000000,
    per_transaction_limit BIGINT DEFAULT 50000000,
    max_daily_atm_limit BIGINT DEFAULT 200000000,
    max_daily_pos_limit BIGINT DEFAULT 500000000,
    max_daily_online_limit BIGINT DEFAULT 200000000,
    max_per_transaction_limit BIGINT DEFAULT 200000000,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE card_operation_requests (
    request_id UUID PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    card_id UUID NOT NULL REFERENCES cards(card_id),
    operation VARCHAR(50) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    session_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE account_products (
    product_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code VARCHAR(30) UNIQUE NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    account_type VARCHAR(30) NOT NULL,
    currency VARCHAR(5) NOT NULL DEFAULT 'VND',
    min_age INT DEFAULT 18,
    requires_kyc BOOLEAN DEFAULT TRUE,
    monthly_fee BIGINT DEFAULT 0,
    opening_fee BIGINT DEFAULT 0,
    max_accounts_per_customer INT DEFAULT 3,
    is_active BOOLEAN DEFAULT TRUE,
    description TEXT
);

CREATE TABLE chat_sessions (
    session_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(20) NOT NULL,
    title TEXT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMP,
    pipeline_state JSONB,
    transaction_state JSONB,
    card_operation_state JSONB,
    account_operation_state JSONB,
    message_count INTEGER DEFAULT 0,
    active_task_id UUID
);

CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    user_id VARCHAR(20) NOT NULL,
    role VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE agent_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(20) NOT NULL,
    session_id VARCHAR(100),
    domain VARCHAR(50) NOT NULL,
    memory_key VARCHAR(100) NOT NULL,
    memory_value JSONB NOT NULL,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_memory UNIQUE (user_id, session_id, domain, memory_key)
);

CREATE TABLE conversation_tasks (
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
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE UNIQUE INDEX idx_ext_bank_acc_unique ON external_bank_accounts(account_no, bank_code);
CREATE INDEX idx_accounts_cif ON accounts(cif_no);
CREATE INDEX idx_cards_cif ON cards(cif_no);
CREATE INDEX idx_beneficiaries_cif ON beneficiaries(cif_no);
CREATE INDEX idx_transactions_cif ON transactions(cif_no);
CREATE INDEX idx_transactions_time ON transactions(transaction_time);
CREATE INDEX idx_transactions_type ON transactions(transaction_type);
CREATE INDEX idx_transactions_cif_time ON transactions(cif_no, transaction_time);
CREATE INDEX idx_transactions_cif_type ON transactions(cif_no, transaction_type);
CREATE INDEX idx_action_requests_cif ON action_requests(cif_no);
CREATE INDEX idx_audit_logs_action ON audit_logs(action_id);
CREATE INDEX idx_cba_cif ON customer_biller_accounts(cif_no);
CREATE INDEX idx_fraud_reports_reporter ON fraud_reports(reporter_cif_no);
CREATE INDEX idx_fraud_reports_account ON fraud_reports(reported_account_no, reported_bank_code);
CREATE INDEX idx_reported_accounts_lookup ON reported_accounts(account_no, bank_code);
CREATE INDEX idx_reported_customers_cif ON reported_customers(cif_no);
CREATE INDEX idx_fraud_decisions_action ON fraud_decisions(action_id);
CREATE INDEX idx_bills_lookup ON bills(biller_code, customer_bill_code, status);
CREATE INDEX idx_interest_rates_lookup ON interest_rates(product_type, term_months, status, effective_from);
CREATE INDEX idx_chat_sessions_user_updated_at ON chat_sessions(user_id, updated_at DESC);
CREATE INDEX idx_chat_messages_session_created_at ON chat_messages(session_id, created_at DESC);
CREATE INDEX idx_agent_memory_lookup ON agent_memory(user_id, domain);
CREATE INDEX idx_agent_memory_expires ON agent_memory(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX idx_conversation_tasks_session_lifecycle ON conversation_tasks(session_id, lifecycle, updated_at DESC);
CREATE INDEX idx_conversation_tasks_user_updated ON conversation_tasks(user_id, updated_at DESC);
