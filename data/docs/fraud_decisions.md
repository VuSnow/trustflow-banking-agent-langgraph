# fraud_decisions

## 1. Muc dich bang

Luu ket qua screening truoc khi chuyen tien.

**Nhom:** Fraud detection / transaction screening

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| decision_id | UUID string | Dinh danh ban ghi | ac365eea-48c4-514a-8d7b-15f2da68abae, 04b38cb9-6fec-5a4f-9308-3fb2da436cda, c66f6210-3bd6-55b4-85e6-e33059ab938e | No | - | - |
| action_id | UUID string | Dinh danh ban ghi | d97f11b6-08c6-5f73-8e6b-a740f087f632, 774ac552-112c-5961-9004-5b534c309a2f, d0ed39b1-093d-59b1-b922-51dd660f9625 | No | FK -> action_requests.action_id | - |
| receiver_account_no | numeric | Ma/so nghiep vu | 3045319433, 215226557676, 2971024817 | No | - | - |
| receiver_bank_code | enum string | Ma tham chieu nghiep vu | STB, VIB, TCB | No | - | - |
| matched_report_count | boolean | Truong du lieu nghiep vu | 0, 0, 0 | No | - | - |
| risk_score | numeric | Truong du lieu nghiep vu | 0.0, 0.0, 0.0 | No | - | - |
| risk_level | enum string | Trang thai/muc do theo workflow | NONE, NONE, NONE | No | - | - |
| decision | enum string | Trang thai/muc do theo workflow | ALLOW, ALLOW, ALLOW | No | - | - |
| reason_codes | JSON string | Truong du lieu nghiep vu | [], [], [] | No | - | JSON payload phuc vu truy vet hoac dieu phoi flow |
| created_at | timestamp string | Moc thoi gian | 2026-04-21 10:14:08, 2026-04-09 15:40:38, 2026-04-09 03:00:58 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| receiver_bank_code | ACB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | BIDV | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | CTG | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | MB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | STB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | TCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | TPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | VCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| receiver_bank_code | VIB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- fraud_decisions.action_id -> action_requests.action_id

## 6. Simple Usage Examples

```sql
SELECT * FROM fraud_decisions LIMIT 5;
```
