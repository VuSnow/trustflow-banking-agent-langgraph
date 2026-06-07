"""
Export CSV files to SQL files.
Usage: python export_to_sql.py

Output:
  ../sql/01_schema.sql       - DDL (DROP/CREATE/INDEX)
  ../sql/02_*.sql            - INSERT statements per CSV table
  ../sql/99_post_load_seed.sql - Derived seed data for non-CSV tables
  ../sql/all_in_one.sql      - Schema + data + derived seeds
"""

import csv
import os
from pathlib import Path

BASE_DIR = Path(os.path.dirname(__file__)).parent
DATA_DIR = BASE_DIR / "csv"
SQL_DIR = BASE_DIR / "sql"

INDEX_NAMES = [
    "idx_ext_bank_acc_unique",
    "idx_accounts_cif",
    "idx_cards_cif",
    "idx_beneficiaries_cif",
    "idx_transactions_cif",
    "idx_transactions_time",
    "idx_transactions_type",
    "idx_transactions_cif_time",
    "idx_transactions_cif_type",
    "idx_action_requests_cif",
    "idx_audit_logs_action",
    "idx_cba_cif",
    "idx_fraud_reports_reporter",
    "idx_fraud_reports_account",
    "idx_reported_accounts_lookup",
    "idx_reported_customers_cif",
    "idx_fraud_decisions_action",
    "idx_bills_lookup",
    "idx_interest_rates_lookup",
    "idx_chat_sessions_user_updated_at",
    "idx_chat_messages_session_created_at",
    "idx_agent_memory_lookup",
    "idx_agent_memory_expires",
    "idx_conversation_tasks_session_lifecycle",
    "idx_conversation_tasks_user_updated",
]

DROP_TABLES = [
    "conversation_tasks",
    "chat_messages",
    "card_operation_requests",
    "card_limits",
    "card_controls",
    "account_products",
    "agent_memory",
    "fraud_decisions",
    "reported_customers",
    "reported_accounts",
    "fraud_reports",
    "audit_logs",
    "api_call_logs",
    "action_requests",
    "transactions",
    "transaction_categories",
    "bills",
    "interest_rates",
    "customer_biller_accounts",
    "billers",
    "merchants",
    "beneficiaries",
    "cards",
    "accounts",
    "external_bank_accounts",
    "customers",
    "chat_sessions",
]

# CSV-backed tables in dependency-safe load order.
TABLES = [
    "customers",
    "accounts",
    "cards",
    "beneficiaries",
    "merchants",
    "billers",
    "customer_biller_accounts",
    "bills",
    "interest_rates",
    "transaction_categories",
    "transactions",
    "action_requests",
    "api_call_logs",
    "audit_logs",
    "fraud_reports",
    "reported_accounts",
    "reported_customers",
    "fraud_decisions",
    "external_bank_accounts",
]

BOOL_FIELDS = {
    "is_saved",
    "requires_confirmation",
    "requires_otp",
    "has_evidence",
    "is_primary",
}

INT_FIELDS = {
    "id",
    "balance",
    "available_balance",
    "credit_limit",
    "available_limit",
    "amount",
    "balance_after",
    "http_status",
    "confidence_score",
    "valid_report_count",
    "unique_reporter_count",
    "total_reported_amount",
    "avg_confidence_score",
    "reported_account_count",
    "matched_report_count",
    "min_amount",
    "max_amount",
    "term_months",
}

FLOAT_FIELDS = {
    "risk_score",
    "annual_rate",
    "amount_due",
}

JSON_FIELDS = {
    "api_payload",
    "resolved_entities",
    "missing_fields",
    "request_payload",
    "response_payload",
    "event_payload",
    "reason_codes",
}


def _build_schema_sql() -> str:
    drop_indexes = "\n".join(f"DROP INDEX IF EXISTS {name};" for name in INDEX_NAMES)
    drop_tables = "\n".join(f"DROP TABLE IF EXISTS {name} CASCADE;" for name in DROP_TABLES)

    body = """\
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
"""

    return (
        "-- ============================================================\n"
        "-- TrustFlow Banking Agent - Database Schema (PostgreSQL)\n"
        "-- Generated from CSV data\n"
        "-- ============================================================\n\n"
        "-- Drop indexes (safe cleanup)\n"
        f"{drop_indexes}\n\n"
        "-- Drop tables in reverse dependency order\n"
        f"{drop_tables}\n\n"
        f"{body}"
    )


SCHEMA_SQL = _build_schema_sql()

POST_LOAD_SQL = """\
-- ============================================================
-- POST-LOAD SEEDS FOR NON-CSV TABLES
-- ============================================================

INSERT INTO account_products (
    product_code, product_name, account_type, currency, min_age,
    requires_kyc, monthly_fee, opening_fee, max_accounts_per_customer,
    is_active, description
) VALUES
    ('CURRENT_VND', 'Tai khoan thanh toan VND', 'PAYMENT', 'VND', 18, TRUE, 0, 0, 3, TRUE,
     'Tai khoan thanh toan noi dia, dung cho chi tieu hang ngay va nhan luong.'),
    ('CURRENT_USD', 'Tai khoan thanh toan USD', 'PAYMENT', 'USD', 18, TRUE, 50000, 0, 2, TRUE,
     'Tai khoan ngoai te USD cho giao dich quoc te.'),
    ('SAVINGS_VND', 'Tai khoan tiet kiem VND', 'SAVINGS', 'VND', 18, TRUE, 0, 0, 5, TRUE,
     'Tai khoan tiet kiem khong ky han, lai suat theo so du.')
ON CONFLICT (product_code) DO NOTHING;

INSERT INTO card_controls (
    card_id,
    online_payment_enabled,
    international_payment_enabled,
    atm_withdrawal_enabled,
    pos_payment_enabled,
    contactless_enabled,
    updated_at
)
SELECT
    card_id,
    TRUE,
    CASE WHEN card_network IN ('VISA', 'MASTERCARD') THEN TRUE ELSE FALSE END,
    TRUE,
    TRUE,
    CASE WHEN card_network IN ('VISA', 'MASTERCARD') THEN TRUE ELSE FALSE END,
    CURRENT_TIMESTAMP
FROM cards
ON CONFLICT (card_id) DO NOTHING;

INSERT INTO card_limits (
    card_id,
    daily_atm_limit,
    daily_pos_limit,
    daily_online_limit,
    per_transaction_limit,
    max_daily_atm_limit,
    max_daily_pos_limit,
    max_daily_online_limit,
    max_per_transaction_limit,
    updated_at
)
SELECT
    card_id,
    CASE WHEN card_type = 'CREDIT' THEN 100000000 ELSE 50000000 END,
    CASE WHEN card_type = 'CREDIT' THEN 200000000 ELSE 100000000 END,
    CASE WHEN card_type = 'CREDIT' THEN 100000000 ELSE 30000000 END,
    CASE WHEN card_type = 'CREDIT' THEN 100000000 ELSE 50000000 END,
    200000000,
    500000000,
    200000000,
    200000000,
    CURRENT_TIMESTAMP
FROM cards
ON CONFLICT (card_id) DO NOTHING;
"""


def escape_sql_string(val: str) -> str:
    return val.replace("'", "''")


def format_value(col: str, val: str) -> str:
    if val == "" or val is None:
        return "NULL"

    if col in BOOL_FIELDS:
        return "TRUE" if str(val).strip().lower() in ("true", "1", "yes") else "FALSE"

    if col in INT_FIELDS:
        try:
            return str(int(float(val)))
        except (TypeError, ValueError):
            return "NULL"

    if col in FLOAT_FIELDS:
        try:
            return str(float(val))
        except (TypeError, ValueError):
            return "NULL"

    if col in JSON_FIELDS:
        return f"'{escape_sql_string(val)}'::jsonb"

    return f"'{escape_sql_string(val)}'"


def generate_inserts(table_name: str) -> tuple[str, int]:
    csv_path = DATA_DIR / f"{table_name}.csv"
    if not csv_path.exists():
        return "", 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return "", 0

    columns = list(rows[0].keys())
    col_names = ", ".join(columns)

    lines = [f"-- {table_name} ({len(rows)} rows)"]
    lines.append(f"INSERT INTO {table_name} ({col_names}) VALUES")

    value_lines = []
    for row in rows:
        values = ", ".join(format_value(col, row[col]) for col in columns)
        value_lines.append(f"  ({values})")

    lines.append(",\n".join(value_lines) + ";\n")
    return "\n".join(lines), len(rows)


def main() -> None:
    SQL_DIR.mkdir(parents=True, exist_ok=True)

    # Remove only generator-owned files to avoid touching unrelated migration SQLs.
    for table in TABLES:
        for old_file in SQL_DIR.glob(f"[0-9][0-9]_{table}.sql"):
            old_file.unlink()

    for filename in ("01_schema.sql", "99_post_load_seed.sql", "all_in_one.sql"):
        old_path = SQL_DIR / filename
        if old_path.exists():
            old_path.unlink()

    schema_path = SQL_DIR / "01_schema.sql"
    with open(schema_path, "w", encoding="utf-8") as f:
        f.write(SCHEMA_SQL)
    print(f"Written: {schema_path}")

    print("\nWriting per-table SQL files:")
    total_rows = 0
    for i, table in enumerate(TABLES, start=1):
        insert_sql, count = generate_inserts(table)
        if not insert_sql:
            continue

        file_num = f"{i + 1:02d}"  # 01 reserved for schema
        table_path = SQL_DIR / f"{file_num}_{table}.sql"
        with open(table_path, "w", encoding="utf-8") as f:
            f.write(f"-- {table} data\n")
            f.write("BEGIN;\n\n")
            f.write(insert_sql)
            f.write("\nCOMMIT;\n")

        total_rows += count
        print(f"  {table_path.name}: {count} rows")

    post_load_path = SQL_DIR / "99_post_load_seed.sql"
    with open(post_load_path, "w", encoding="utf-8") as f:
        f.write("-- Derived seeds for non-CSV tables\n")
        f.write("BEGIN;\n\n")
        f.write(POST_LOAD_SQL)
        f.write("\nCOMMIT;\n")
    print(f"  {post_load_path.name}: written")

    print(f"\nTotal CSV rows exported: {total_rows}")

    all_path = SQL_DIR / "all_in_one.sql"
    with open(all_path, "w", encoding="utf-8") as f:
        f.write("-- ============================================================\n")
        f.write("-- TrustFlow Banking Agent - Schema + Data (PostgreSQL)\n")
        f.write("-- Run: psql -d banking_mcp_test -f all_in_one.sql\n")
        f.write("-- ============================================================\n\n")

        f.write(SCHEMA_SQL)
        f.write("\n\n")

        f.write("BEGIN;\n\n")
        for table in TABLES:
            insert_sql, _ = generate_inserts(table)
            if insert_sql:
                f.write(insert_sql)
                f.write("\n")
        f.write(POST_LOAD_SQL)
        f.write("\nCOMMIT;\n")

    print(f"Written: {all_path}")
    print("\nUsage:")
    print(f"  psql -d banking_mcp_test -f {all_path}")
    print(f"  psql -d banking_mcp_test -f {schema_path}")


if __name__ == "__main__":
    main()
