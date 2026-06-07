-- reported_customers data
BEGIN;

-- reported_customers (3 rows)
INSERT INTO reported_customers (reported_customer_id, cif_no, reported_account_count, valid_report_count, total_reported_amount, risk_score, risk_level, status, created_at, updated_at) VALUES
  ('131ec971-efed-5a6b-9f41-6e41b2e264d5', 'CIF000070', 2, 2, 82851112, 0.7, 'FROZEN', 'ACTIVE', '2026-05-16 10:51:32', '2026-05-31 20:57:06'),
  ('26d68bc2-633d-51a3-898e-2528febcc262', 'CIF000082', 1, 2, 31960662, 0.4, 'WATCH', 'ACTIVE', '2026-05-01 22:53:53', '2026-05-27 17:42:37'),
  ('8ce963ae-702f-5ba1-bba3-63599123eff0', 'CIF000075', 1, 3, 23149104, 0.4, 'WATCH', 'ACTIVE', '2026-05-04 07:34:01', '2026-05-24 23:06:24');

COMMIT;
