# reported_accounts

## 1. Muc dich bang

Bang tong hop muc do rui ro theo tai khoan bi bao cao.

**Nhom:** Fraud detection / transaction screening

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| reported_account_id | UUID string | Dinh danh ban ghi | f420f3a9-42b3-5536-9d7b-a7e0a3aec844, 562536e4-5ea2-5aaa-b816-a0699f710fb6, b9474b94-10b8-549e-bb72-ce33ad23a3a7 | No | PK | - |
| account_no | numeric | Ma/so nghiep vu | 26940539672, 8725686211022, 2347851961 | No | - | - |
| bank_code | enum string | Ma tham chieu nghiep vu | STB, MB, VCB | No | - | - |
| linked_customer_cif | string | Truong du lieu nghiep vu | - | Yes | - | - |
| valid_report_count | boolean | Truong du lieu nghiep vu | 1, 1, 1 | No | - | - |
| unique_reporter_count | boolean | Truong du lieu nghiep vu | 1, 1, 1 | No | - | - |
| total_reported_amount | numeric | Truong du lieu nghiep vu | 36494500, 35306378, 48336472 | No | - | - |
| avg_confidence_score | numeric | Truong du lieu nghiep vu | 100, 80, 55 | No | - | - |
| risk_score | numeric | Truong du lieu nghiep vu | 0.95, 0.95, 0.25 | No | - | - |
| risk_level | enum string | Trang thai/muc do theo workflow | CRITICAL, CRITICAL, LOW | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | ACTIVE, ACTIVE, ACTIVE | No | - | Gia tri phai khop enum cua workflow hien tai |
| first_reported_at | timestamp string | Moc thoi gian | 2026-05-30 07:06:28, 2026-05-30 04:58:45, 2026-05-26 00:10:50 | No | - | - |
| last_reported_at | timestamp string | Moc thoi gian | 2026-05-30 07:06:28, 2026-05-30 04:58:45, 2026-05-26 00:10:50 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| bank_code | MB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | STB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | TCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | TPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | VCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | VIB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| bank_code | VPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_level | CRITICAL | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| risk_level | LOW | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- Khong co quan he FK truc tiep.

## 6. Simple Usage Examples

```sql
SELECT * FROM reported_accounts LIMIT 5;
```
