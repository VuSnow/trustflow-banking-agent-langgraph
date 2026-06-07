-- interest_rates data
BEGIN;

-- interest_rates (13 rows)
INSERT INTO interest_rates (id, product_code, product_type, product_name, currency, term_months, annual_rate, min_amount, max_amount, customer_segment, channel, effective_from, effective_to, status, created_at) VALUES
  (NULL, 'DEMAND_VND', 'SAVINGS', 'Tien gui khong ky han', 'VND', NULL, 0.1, 0, NULL, 'ALL', 'ALL', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_ONLINE_1M', 'SAVINGS', 'Tiet kiem online 1 thang', 'VND', 1, 2.9, 1000000, NULL, 'ALL', 'ONLINE', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_ONLINE_3M', 'SAVINGS', 'Tiet kiem online 3 thang', 'VND', 3, 3.4, 1000000, NULL, 'ALL', 'ONLINE', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_ONLINE_6M', 'SAVINGS', 'Tiet kiem online 6 thang', 'VND', 6, 4.5, 1000000, NULL, 'ALL', 'ONLINE', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_ONLINE_12M', 'SAVINGS', 'Tiet kiem online 12 thang', 'VND', 12, 5.0, 1000000, NULL, 'ALL', 'ONLINE', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_ONLINE_24M', 'SAVINGS', 'Tiet kiem online 24 thang', 'VND', 24, 5.2, 1000000, NULL, 'ALL', 'ONLINE', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_COUNTER_3M', 'SAVINGS', 'Tiet kiem quay 3 thang', 'VND', 3, 3.2, 5000000, NULL, 'ALL', 'COUNTER', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_COUNTER_6M', 'SAVINGS', 'Tiet kiem quay 6 thang', 'VND', 6, 4.3, 5000000, NULL, 'ALL', 'COUNTER', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_COUNTER_12M', 'SAVINGS', 'Tiet kiem quay 12 thang', 'VND', 12, 4.8, 5000000, NULL, 'ALL', 'COUNTER', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'SAVINGS_COUNTER_24M', 'SAVINGS', 'Tiet kiem quay 24 thang', 'VND', 24, 5.0, 5000000, NULL, 'ALL', 'COUNTER', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'LOAN_PERSONAL_12M', 'LOAN', 'Vay tieu dung 12 thang', 'VND', 12, 8.5, 10000000, NULL, 'ALL', 'ALL', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'LOAN_PERSONAL_24M', 'LOAN', 'Vay tieu dung 24 thang', 'VND', 24, 9.0, 10000000, NULL, 'ALL', 'ALL', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00'),
  (NULL, 'LOAN_MORTGAGE', 'LOAN', 'Vay mua nha', 'VND', 240, 7.2, 100000000, NULL, 'ALL', 'ALL', '2026-01-01', NULL, 'ACTIVE', '2026-01-01 00:00:00');

COMMIT;
