# reported_customers

## 1. Muc dich bang

Bang tong hop muc do rui ro theo CIF bi bao cao.

**Nhom:** Fraud detection / transaction screening

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| reported_customer_id | UUID string | Dinh danh ban ghi | 131ec971-efed-5a6b-9f41-6e41b2e264d5, 26d68bc2-633d-51a3-898e-2528febcc262, 8ce963ae-702f-5ba1-bba3-63599123eff0 | No | PK | - |
| cif_no | enum string | Ma/so nghiep vu | CIF000070, CIF000082, CIF000075 | No | FK -> customers.cif_no | - |
| reported_account_count | numeric | Truong du lieu nghiep vu | 2, 1, 1 | No | - | - |
| valid_report_count | numeric | Truong du lieu nghiep vu | 2, 2, 3 | No | - | - |
| total_reported_amount | numeric | Truong du lieu nghiep vu | 82851112, 31960662, 23149104 | No | - | - |
| risk_score | numeric | Truong du lieu nghiep vu | 0.7, 0.4, 0.4 | No | - | - |
| risk_level | enum string | Trang thai/muc do theo workflow | FROZEN, WATCH, WATCH | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2026-05-16 10:51:32, 2026-05-01 22:53:53, 2026-05-04 07:34:01 | No | - | - |
| updated_at | timestamp string | Moc thoi gian | 2026-05-31 20:57:06, 2026-05-27 17:42:37, 2026-05-24 23:06:24 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| cif_no | CIF000070 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| cif_no | CIF000075 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| cif_no | CIF000082 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_level | FROZEN | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_level | WATCH | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- reported_customers.cif_no -> customers.cif_no

## 6. Simple Usage Examples

```sql
SELECT * FROM reported_customers LIMIT 5;
SELECT * FROM reported_customers WHERE cif_no = 'CIF000001' LIMIT 10;
```
