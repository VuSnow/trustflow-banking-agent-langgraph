# fraud_reports

## 1. Muc dich bang

Luu bao cao lua dao tu nguoi dung.

**Nhom:** Fraud detection / transaction screening

## 2. Ngu canh nghiep vu

- Bang nay phuc vu luong xu ly cua cac agent trong he thong TrustFlow.
- Du lieu duoc dung de truy van read model, xac thuc thong tin va truy vet audit.
- Day la mock data cho demo, khong phai core ledger van hanh that.

## 3. Columns

| Column | Type | Meaning | Example Values From Data | Nullable | Key / Relationship | Notes |
|---|---|---|---|---|---|---|
| report_id | UUID string | Dinh danh ban ghi | 1c2372a8-ef70-5c8c-b6a0-d321c8b22f2e, c11aaec2-2f0b-5159-a3ff-771d40f57fb4, e8f9f896-7531-504e-9a28-56ca252b4dad | No | - | - |
| reporter_cif_no | enum string | Ma/so nghiep vu | CIF000058, CIF000060, CIF000015 | No | FK -> customers.cif_no | - |
| transaction_ref | enum string | Truong du lieu nghiep vu | TXN202605003258, TXN202602000531, TXN202601000379 | No | FK -> transactions.transaction_ref | - |
| reported_account_no | numeric | Ma/so nghiep vu | 26940539672, 8725686211022, 2347851961 | No | - | - |
| reported_bank_code | enum string | Ma tham chieu nghiep vu | STB, MB, VCB | No | - | - |
| reported_customer_cif | string | Truong du lieu nghiep vu | - | Yes | - | - |
| fraud_type | enum string | Truong du lieu nghiep vu | SHOPPING_SCAM, SHOPPING_SCAM, SHOPPING_SCAM | No | - | - |
| contact_channel | enum string | Truong du lieu nghiep vu | ZALO, TELEGRAM, FACEBOOK | No | - | - |
| aftermath | enum string | Truong du lieu nghiep vu | LINK_GONE, BLOCKED_CONTACT, OTHER | No | - | - |
| reason_text | string | Noi dung mo ta | Bi lua dao qua zalo, link gone, Bi lua dao qua telegram, blocked contact, Bi lua dao qua facebook, other | No | - | - |
| has_evidence | boolean | Truong du lieu nghiep vu | True, True, False | No | - | Co/khong theo logic nghiep vu |
| confidence_score | numeric | Truong du lieu nghiep vu | 100, 80, 55 | No | - | - |
| status | enum string | Trang thai/muc do theo workflow | VALIDATED, VALIDATED, SUBMITTED | No | - | Gia tri phai khop enum cua workflow hien tai |
| created_at | timestamp string | Moc thoi gian | 2026-05-30 07:06:28, 2026-05-30 04:58:45, 2026-05-26 00:10:50 | No | - | - |

## 4. Important Values / Enums

| Column | Value | Meaning | Example Use Case |
|---|---|---|---|
| reporter_cif_no | CIF000002 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000004 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000015 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000026 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000048 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000058 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000060 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reporter_cif_no | CIF000098 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202601000215 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202601000379 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202602000531 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202602000902 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202602000992 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202604001743 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202604002845 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| transaction_ref | TXN202605003258 | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | MB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | STB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | TCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | TPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | VCB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | VIB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| reported_bank_code | VPB | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| fraud_type | LOAN_SCAM | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| fraud_type | OTHER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| fraud_type | ROMANCE_SCAM | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| fraud_type | SHOPPING_SCAM | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| contact_channel | FACEBOOK | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| contact_channel | OTHER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| contact_channel | TELEGRAM | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| contact_channel | WEBSITE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| contact_channel | ZALO | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| aftermath | ASKED_MORE_MONEY | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| aftermath | BLOCKED_CONTACT | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| aftermath | LINK_GONE | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| aftermath | NO_GOODS | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| aftermath | OTHER | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | CONFIRMED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | SUBMITTED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |
| status | VALIDATED | Gia tri enum trong du lieu | Loc/truy van theo trang thai/loai |

## 5. Relationships

- fraud_reports.reporter_cif_no -> customers.cif_no
- fraud_reports.transaction_ref -> transactions.transaction_ref

## 6. Simple Usage Examples

```sql
SELECT * FROM fraud_reports LIMIT 5;
```
