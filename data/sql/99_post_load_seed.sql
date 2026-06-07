-- Derived seeds for non-CSV tables
BEGIN;

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

COMMIT;
