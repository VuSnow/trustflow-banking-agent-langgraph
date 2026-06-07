-- fraud_reports data
BEGIN;

-- fraud_reports (8 rows)
INSERT INTO fraud_reports (report_id, reporter_cif_no, transaction_ref, reported_account_no, reported_bank_code, reported_customer_cif, fraud_type, contact_channel, aftermath, reason_text, has_evidence, confidence_score, status, created_at) VALUES
  ('1c2372a8-ef70-5c8c-b6a0-d321c8b22f2e', 'CIF000058', 'TXN202605003258', '26940539672', 'STB', NULL, 'SHOPPING_SCAM', 'ZALO', 'LINK_GONE', 'Bi lua dao qua zalo, link gone', TRUE, 100, 'VALIDATED', '2026-05-30 07:06:28'),
  ('c11aaec2-2f0b-5159-a3ff-771d40f57fb4', 'CIF000060', 'TXN202602000531', '8725686211022', 'MB', NULL, 'SHOPPING_SCAM', 'TELEGRAM', 'BLOCKED_CONTACT', 'Bi lua dao qua telegram, blocked contact', TRUE, 80, 'VALIDATED', '2026-05-30 04:58:45'),
  ('e8f9f896-7531-504e-9a28-56ca252b4dad', 'CIF000015', 'TXN202601000379', '2347851961', 'VCB', NULL, 'SHOPPING_SCAM', 'FACEBOOK', 'OTHER', 'Bi lua dao qua facebook, other', FALSE, 55, 'SUBMITTED', '2026-05-26 00:10:50'),
  ('6b371e58-f6e9-55cf-895e-3590fe878dd2', 'CIF000098', 'TXN202604001743', '7352287056227', 'TCB', NULL, 'LOAN_SCAM', 'WEBSITE', 'ASKED_MORE_MONEY', 'Bi lua dao qua website, asked more money', FALSE, 70, 'CONFIRMED', '2026-05-31 17:47:17'),
  ('318d9aba-ab40-5daf-9d46-dcab67637630', 'CIF000048', 'TXN202601000215', '3122068155', 'TPB', NULL, 'ROMANCE_SCAM', 'ZALO', 'LINK_GONE', 'Bi lua dao qua zalo, link gone', TRUE, 80, 'VALIDATED', '2026-05-14 14:10:47'),
  ('2ef631da-42ab-503c-a616-f5e909c01b88', 'CIF000002', 'TXN202602000992', '85445770299', 'MB', NULL, 'SHOPPING_SCAM', 'TELEGRAM', 'BLOCKED_CONTACT', 'Bi lua dao qua telegram, blocked contact', TRUE, 80, 'VALIDATED', '2026-05-07 04:22:00'),
  ('cfd17d65-7e5e-567b-8b43-5670eed249e0', 'CIF000026', 'TXN202602000902', '2415027456449', 'VPB', NULL, 'OTHER', 'OTHER', 'NO_GOODS', 'Bi lua dao qua other, no goods', TRUE, 65, 'CONFIRMED', '2026-05-29 18:21:12'),
  ('4f9c6d99-7ce2-5341-bc50-5177ec0c0a02', 'CIF000004', 'TXN202604002845', '654420949407', 'VIB', NULL, 'SHOPPING_SCAM', 'ZALO', 'ASKED_MORE_MONEY', 'Bi lua dao qua zalo, asked more money', TRUE, 80, 'VALIDATED', '2026-05-18 20:18:09');

COMMIT;
